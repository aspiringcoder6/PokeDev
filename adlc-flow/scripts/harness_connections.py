"""Configure private Harness connections or serve the scoped local gateways.

Generated files contain credentials and must stay in ignored data directories.
No model key is accepted. Setup POSTs are never automatically retried.
"""

# ruff: noqa: EM101, PLR2004 - bounded setup checks and fixed errors; never print credentials.
import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid5

import httpx
from dotenv import load_dotenv, set_key

from langflow.adlc.memory_gateway_local import BACKEND_REVISION, CogneeDocumentReader, LocalMemorySettings

FLOW = Path(__file__).resolve().parents[1]
PRIVATE = FLOW / "data/harness-connections"
ENV_FILE = FLOW / "data/harness-demo/demo.env"
GATEWAY_FILE = PRIVATE / "memory-gateway.json"
REGISTRY_FILE = PRIVATE / "memory-registry.json"
INTENT_FILE = PRIVATE / "memory-setup-intent.json"


def private_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def configure(values):
    if not ENV_FILE.is_file():
        raise RuntimeError("HARNESS_PRIVATE_SETTINGS_MISSING")
    for key, value in values.items():
        set_key(ENV_FILE, key, str(value), quote_mode="always")


async def setup_memory(owner, repository, source_commit):
    project = uuid5(owner, "github:" + repository)
    if GATEWAY_FILE.exists():
        raw = json.loads(GATEWAY_FILE.read_bytes())
        settings = LocalMemorySettings.model_validate(raw)
        binding = next(b for b in settings.bindings if b.owner_id == owner and b.project_id == project)
        chunks = await CogneeDocumentReader(settings).documents(binding)
        if not chunks:
            raise RuntimeError("MEMORY_BACKEND_EMPTY_OR_EXPIRED")
        print("Existing memory binding read from Cognee; no document was re-ingested.", flush=True)
        return project
    if INTENT_FILE.exists():
        raise RuntimeError("MEMORY_SETUP_UNCONFIRMED_INSPECT_INTENT_BEFORE_RETRY")
    credential = {
        "owner_id": str(owner),
        "project_id": str(project),
        "email": "harness-" + project.hex + "@example.com",
        "password": secrets.token_urlsafe(48),
        "token": secrets.token_urlsafe(48),
    }
    # Preserve credentials/intent before any API mutation; no lost/unknown POST is replayed.
    private_write(INTENT_FILE, {"phase": "ALLOCATED", **credential})
    api = "http://127.0.0.1:8010"
    async with httpx.AsyncClient(base_url=api, timeout=90, trust_env=False, follow_redirects=False) as client:
        registered = await client.post(
            "/api/v1/auth/register", json={"email": credential["email"], "password": credential["password"]}
        )
        if registered.status_code != 201:
            raise RuntimeError("MEMORY_ACCOUNT_CREATION_UNCONFIRMED")
        print("Created an isolated local Cognee project account.", flush=True)
        login = await client.post(
            "/api/v1/auth/login", data={"username": credential["email"], "password": credential["password"]}
        )
        if login.status_code != 200:
            raise RuntimeError("MEMORY_LOGIN_FAILED")
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        dataset = await client.post("/api/v1/datasets", json={"name": "adlc-project-" + project.hex})
        if dataset.status_code not in {200, 201}:
            raise RuntimeError("MEMORY_DATASET_CREATION_UNCONFIRMED")
        dataset_id = str(UUID(dataset.json()["id"]))
        print("Created the project-owned memory dataset.", flush=True)
        timestamp = datetime.now(timezone.utc)
        note = {
            "schema_version": "0.1",
            "owner_id": str(owner),
            "project_id": str(project),
            "text": (
                "Python pagination uses one-based pages: offset=(page-1)*size. "
                "Python bool is a subclass of int; page and size validation must reject booleans. "
                "This is advisory project context, not permission or verification evidence. "
                "Keep protected tests immutable and publish only the exact human-approved candidate."
            ),
            "revision": "pagination-conventions-1",
            "recorded_at": timestamp.isoformat(),
            "expires_at": (timestamp + timedelta(days=7)).isoformat(),
            "source_commit": source_commit,
        }
        note_bytes = json.dumps(note, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        added = await client.post(
            "/api/v1/add",
            data={"datasetId": dataset_id, "run_in_background": "false", "labels": '["adlc-project-context-v1"]'},
            files={"data": ("pagination-conventions.txt", note_bytes, "text/plain")},
        )
        if added.status_code != 200:
            raise RuntimeError("MEMORY_DOCUMENT_INGESTION_UNCONFIRMED")
        listed = await client.get(f"/api/v1/datasets/{dataset_id}/data", params={"limit": 2})
        if listed.status_code != 200 or len(listed.json()) != 1:
            raise RuntimeError("MEMORY_DOCUMENT_ID_UNCONFIRMED")
        data_id = str(UUID(listed.json()[0]["id"]))
        raw_document = await client.get(f"/api/v1/datasets/{dataset_id}/data/{data_id}/raw")
        if raw_document.status_code != 200 or raw_document.content != note_bytes:
            raise RuntimeError("MEMORY_DOCUMENT_READBACK_MISMATCH")
        digest = "sha256:" + hashlib.sha256(note_bytes).hexdigest()
    raw = {
        "schema_version": "0.1",
        "backend_url": api,
        "backend_revision": BACKEND_REVISION,
        "bindings": [{**credential, "dataset_id": dataset_id, "documents": [{"data_id": data_id, "digest": digest}]}],
    }
    settings = LocalMemorySettings.model_validate(raw)
    chunks = await CogneeDocumentReader(settings).documents(settings.bindings[0])
    if len(chunks) != 1 or chunks[0].text != note["text"]:
        raise RuntimeError("MEMORY_GATEWAY_READBACK_MISMATCH")
    private_write(GATEWAY_FILE, raw)
    private_write(
        REGISTRY_FILE,
        {
            "schema_version": "0.1",
            "bindings": [
                {
                    "owner_id": str(owner),
                    "project_id": str(project),
                    "url": "http://127.0.0.1:8012/mcp",
                    "token": credential["token"],
                    "backend_revision": BACKEND_REVISION,
                    "isolation_reviewed": True,
                    "no_model_route_reviewed": True,
                    "retention_reviewed": True,
                }
            ],
        },
    )
    private_write(
        PRIVATE / "memory-readback.json",
        {
            "backend": "COGNEE_DOCUMENT_STORE",
            "backend_revision": BACKEND_REVISION,
            "project_id": str(project),
            "dataset_id": dataset_id,
            "data_id": data_id,
            "document_digest": digest,
            "retrieval_verified": True,
            "model_calls": 0,
            "retrieval_mode": "PINNED_DOCUMENT_LEXICAL",
            "expires_at": note["expires_at"],
            "graph_indexed": False,
            "verification_evidence": False,
        },
    )
    private_write(INTENT_FILE, {"phase": "READY", **credential, "dataset_id": dataset_id, "data_id": data_id})
    print("Stored and read back the pinned document through real Cognee API; zero model calls.", flush=True)
    return project


async def check_memory(owner, repository):
    from langflow.adlc.project_memory_client import MemoryMcpClient, load_binding

    project = uuid5(owner, "github:" + repository)
    client = MemoryMcpClient(load_binding(str(owner), project))
    health = await client.operation("health")
    status = await client.operation("status")
    context = await client.operation("context", query="Python pagination bool", top_k=3)
    if status.state != "READY" or not context.chunks:
        raise RuntimeError("MEMORY_GATEWAY_READBACK_EMPTY")
    report = {
        "backend": "COGNEE_DOCUMENT_STORE",
        "backend_revision": health["backend_revision"],
        "ready": health["ready"],
        "retrieval_verified": True,
        "models_used": context.models_used,
        "project_id": str(project),
        "document_count": status.document_count,
        "chunks": [chunk.model_dump(mode="json") for chunk in context.chunks],
        "retrieval_mode": "PINNED_DOCUMENT_LEXICAL",
        "graph_indexed": False,
        "verification_evidence": False,
    }
    private_write(PRIVATE / "memory-gateway-check.json", report)
    print(json.dumps({key: value for key, value in report.items() if key != "chunks"}, indent=2))


def validate_webhook_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != "/webhooks/github/issues"
    ):
        raise RuntimeError("WEBHOOK_HTTPS_URL_INVALID")


async def create_webhook(repository, url):
    from langflow.adlc.harness_demo_sandbox import process

    validate_webhook_url(url)
    if repository != os.getenv("ADLC_HARNESS_GITHUB_REPOSITORY"):
        raise RuntimeError("WEBHOOK_REPOSITORY_MISMATCH")
    metadata = PRIVATE / "github-webhook.json"
    intent = PRIVATE / "github-webhook-intent.json"
    if metadata.exists() or intent.exists():
        raise RuntimeError("WEBHOOK_ALREADY_ALLOCATED_INSPECT_BEFORE_RETRY")
    code, out, _ = await process(
        ["gh", "api", f"repos/{repository}/hooks", "--jq", "[.[]|{id:.id,url:.config.url}]"], credential_context=True
    )
    if code or any(item.get("url") == url for item in json.loads(out)):
        raise RuntimeError("WEBHOOK_EXISTING_CONFIGURATION_UNCONFIRMED")
    secret = os.environ["ADLC_DEMO_GITHUB_WEBHOOK_SECRET"]
    payload = {
        "name": "web",
        "active": True,
        "events": ["issues"],
        "config": {
            "url": url,
            "content_type": "json",
            "insecure_ssl": "0",
            "secret": secret,
        },
    }
    private_write(intent, {"repository": repository, "url": url, "phase": "ALLOCATED"})
    code, out, _ = await process(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{repository}/hooks",
            "--input",
            "-",
            "--jq",
            "{id:.id,url:.config.url,events:.events,active:.active}",
        ],
        data=json.dumps(payload).encode(),
        timeout=30,
        credential_context=True,
    )
    if code:
        raise RuntimeError("WEBHOOK_CREATION_UNCONFIRMED_INSPECT_GITHUB")
    result = json.loads(out)
    if result.get("url") != url or result.get("events") != ["issues"] or not result.get("active"):
        raise RuntimeError("WEBHOOK_CREATION_UNCONFIRMED_INSPECT_GITHUB")
    private_write(metadata, {"repository": repository, **result})
    private_write(intent, {"phase": "READY", "repository": repository, "hook_id": result["id"]})
    print(
        json.dumps(
            {"repository": repository, "hook_id": result["id"], "url": url, "events": result["events"]}, indent=2
        )
    )


async def update_webhook(repository, url):
    from langflow.adlc.harness_demo_sandbox import process

    validate_webhook_url(url)
    metadata = PRIVATE / "github-webhook.json"
    if repository != os.getenv("ADLC_HARNESS_GITHUB_REPOSITORY") or not metadata.is_file():
        raise RuntimeError("WEBHOOK_OWNED_CONFIGURATION_MISSING")
    previous = json.loads(metadata.read_bytes())
    hook_id = previous.get("id")
    if previous.get("repository") != repository or type(hook_id) is not int or hook_id <= 0:
        raise RuntimeError("WEBHOOK_OWNED_CONFIGURATION_INVALID")
    intent = PRIVATE / "webhook-updates" / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    if intent.exists() and json.loads(intent.read_bytes()).get("phase") != "READY":
        raise RuntimeError("WEBHOOK_UPDATE_UNCONFIRMED_INSPECT_GITHUB_BEFORE_RETRY")
    projection = "{id:.id,url:.config.url,events:.events,active:.active}"
    code, out, _ = await process(
        ["gh", "api", f"repos/{repository}/hooks/{hook_id}", "--jq", projection], credential_context=True
    )
    if code:
        raise RuntimeError("WEBHOOK_CURRENT_CONFIGURATION_UNCONFIRMED")
    current = json.loads(out)
    if current != {key: previous[key] for key in ("id", "url", "events", "active")}:
        raise RuntimeError("WEBHOOK_CURRENT_CONFIGURATION_CHANGED")
    if current["events"] != ["issues"] or current["active"] is not True:
        raise RuntimeError("WEBHOOK_CURRENT_SCOPE_CHANGED")
    if current["url"] == url:
        print(json.dumps(previous, indent=2))
        return previous
    private_write(
        intent,
        {
            "phase": "ALLOCATED",
            "repository": repository,
            "hook_id": hook_id,
            "previous_url": previous["url"],
            "url": url,
        },
    )
    payload = {
        "config": {
            "url": url,
            "content_type": "json",
            "insecure_ssl": "0",
            "secret": os.environ["ADLC_DEMO_GITHUB_WEBHOOK_SECRET"],
        }
    }
    code, out, _ = await process(
        ["gh", "api", "--method", "PATCH", f"repos/{repository}/hooks/{hook_id}", "--input", "-", "--jq", projection],
        data=json.dumps(payload).encode(),
        timeout=30,
        credential_context=True,
    )
    if code:
        raise RuntimeError("WEBHOOK_UPDATE_UNCONFIRMED_INSPECT_GITHUB_BEFORE_RETRY")
    result = json.loads(out)
    if result != {"id": hook_id, "url": url, "events": ["issues"], "active": True}:
        raise RuntimeError("WEBHOOK_UPDATE_UNCONFIRMED_INSPECT_GITHUB_BEFORE_RETRY")
    result = {"repository": repository, **result}
    private_write(metadata, result)
    private_write(intent, {"phase": "READY", **result, "previous_url": previous["url"]})
    print(json.dumps(result, indent=2))
    return result


async def create_issue(owner, repository):
    from langflow.adlc.harness_demo_models import REQUIREMENT, digest
    from langflow.adlc.harness_demo_sandbox import process

    if (
        repository != os.getenv("ADLC_HARNESS_GITHUB_REPOSITORY")
        or str(owner) != os.getenv("ADLC_DEMO_GITHUB_OWNER_ID")
        or os.getenv("ADLC_DEMO_GITHUB_ENABLED", "").lower() != "true"
    ):
        raise RuntimeError("ISSUE_OWNED_REPOSITORY_NOT_CONFIGURED")
    metadata = PRIVATE / "github-issue.json"
    intent = PRIVATE / "github-issue-intent.json"
    if metadata.exists():
        result = json.loads(metadata.read_bytes())
        if result.get("repository") != repository:
            raise RuntimeError("ISSUE_REPOSITORY_MISMATCH")
        print(json.dumps(result, indent=2))
        return result  # Completed setup can be inspected without replaying a POST.
    if intent.exists():
        raise RuntimeError("ISSUE_CREATION_UNCONFIRMED_INSPECT_GITHUB_BEFORE_RETRY")
    code, out, _ = await process(
        ["gh", "api", f"repos/{repository}", "--jq", "{id:.id,name:.full_name,push:.permissions.push}"],
        credential_context=True,
    )
    if code:
        raise RuntimeError("ISSUE_REPOSITORY_CHECK_FAILED")
    repo = json.loads(out)
    if (
        repo.get("name") != repository
        or str(repo.get("id")) != os.getenv("ADLC_DEMO_GITHUB_REPOSITORY_ID")
        or repo.get("push") is not True
    ):
        raise RuntimeError("ISSUE_REPOSITORY_SCOPE_MISMATCH")
    private_write(intent, {"phase": "ALLOCATED", "repository": repository, "requirement_digest": digest(REQUIREMENT)})
    payload = {"title": "[ADLC] Pagination task", "body": REQUIREMENT, "labels": ["adlc-harness"]}
    code, out, _ = await process(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{repository}/issues",
            "--input",
            "-",
            "--jq",
            "{number:.number,url:.html_url}",
        ],
        data=json.dumps(payload).encode(),
        timeout=30,
        credential_context=True,
    )
    if code:
        raise RuntimeError("ISSUE_CREATION_UNCONFIRMED_INSPECT_GITHUB_BEFORE_RETRY")
    result = json.loads(out)
    number = result.get("number")
    if (
        type(number) is not int
        or number <= 0
        or result.get("url") != f"https://github.com/{repository}/issues/{number}"
    ):
        raise RuntimeError("ISSUE_CREATION_UNCONFIRMED_INSPECT_GITHUB_BEFORE_RETRY")
    result = {"repository": repository, **result, "awaiting_signed_webhook": True}
    private_write(metadata, result)
    private_write(intent, {"phase": "READY", **result})
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure-memory", action="store_true")
    parser.add_argument("--configure-github", action="store_true")
    parser.add_argument("--check-memory", action="store_true")
    parser.add_argument("--create-webhook")
    parser.add_argument("--update-webhook")
    parser.add_argument("--create-issue", action="store_true")
    parser.add_argument("--owner-id", type=UUID)
    parser.add_argument("--repository")
    parser.add_argument("--repository-id", type=int)
    parser.add_argument("--source-commit")
    parser.add_argument("--serve", choices=["memory", "webhook"])
    args = parser.parse_args()
    if (
        args.configure_memory
        or args.configure_github
        or args.check_memory
        or args.create_webhook
        or args.update_webhook
        or args.create_issue
    ) and (
        not args.owner_id
        or not args.repository
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", args.repository)
    ):
        parser.error("An explicit owner UUID and repository slug are required.")
    if args.configure_memory:
        if not args.source_commit or not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
            parser.error("An exact source commit is required for provenance.")
        project = asyncio.run(setup_memory(args.owner_id, args.repository, args.source_commit))
        configure({"ADLC_DEMO_MEMORY_PROJECT_ID": project, "ADLC_MEMORY_GATEWAY_REGISTRY": REGISTRY_FILE})
        print("Configured project memory; private credentials were not printed.")
    if args.configure_github:
        if not args.repository_id or args.repository_id <= 0:
            parser.error("The verified GitHub repository ID is required.")
        configure(
            {
                "ADLC_HARNESS_GITHUB_REPOSITORY": args.repository,
                "ADLC_DEMO_GITHUB_OWNER_ID": args.owner_id,
                "ADLC_DEMO_GITHUB_REPOSITORY_ID": args.repository_id,
                "ADLC_DEMO_GITHUB_ENABLED": "true",
                "ADLC_DEMO_WEBHOOK_AUTO_PLAN": "true",
            }
        )
        print("Configured the exact owned GitHub repository and human gates.")
    if args.check_memory:
        load_dotenv(ENV_FILE, override=True)
        asyncio.run(check_memory(args.owner_id, args.repository))
    if args.create_webhook:
        load_dotenv(ENV_FILE, override=True)
        asyncio.run(create_webhook(args.repository, args.create_webhook))
    if args.update_webhook:
        load_dotenv(ENV_FILE, override=True)
        asyncio.run(update_webhook(args.repository, args.update_webhook))
    if args.create_issue:
        load_dotenv(ENV_FILE, override=True)
        asyncio.run(create_issue(args.owner_id, args.repository))
    if args.serve:
        load_dotenv(ENV_FILE, override=True)
        import uvicorn

        if args.serve == "memory":
            os.environ["ADLC_MEMORY_LOCAL_GATEWAY_CONFIG"] = str(GATEWAY_FILE)
            target, port = "langflow.adlc.memory_gateway_local:create_app", 8012
        else:
            target, port = "langflow.adlc.github_webhook_edge:create_app", 17862
        uvicorn.run(target, factory=True, host="127.0.0.1", port=port, workers=1)


if __name__ == "__main__":
    main()
