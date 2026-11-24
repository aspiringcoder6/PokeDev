"""Export the current source tree into a separate, clean fork preparation repo.

This deliberately exports files, not Git history or local application state.
No network requests, remote pushes, dependency installs or services are started.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

SOURCE_ROOTS = {"adlc-flow", "adlc_components", "adlc-contracts", "sdk", "docs"}
ROOT_FILES = {"AGENTS.md", "BASELINE.md", "Readme.md", ".gitignore"}
OMIT_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".uv-cache", ".cache", ".langflow", ".auth", ".tmp", "tmp", "build", "dist", "coverage", "logs", "private", "playwright-report", "test-results", "blob-report"}
OMIT_PREFIXES = ("adlc-flow/data/", "docs/report/", "docs/slides/", "docs/kanban-review/", "docs/demos/")
PRIVATE_SUFFIXES = (".db", ".db-shm", ".db-wal", ".sqlite", ".sqlite3", ".sqlite3-shm", ".sqlite3-wal", ".pem", ".key", ".p12", ".pfx", ".log", ".pyc")
PRIVATE_NAMES = {"credentials.json", "token.json", "cookies.json", "storage-state.json", "storage_state.json", "storagestate.json", "id_rsa", "id_ed25519", ".git-credentials", "opencode.json"}
BRAND_SUFFIXES = {".tsx", ".ts", ".json", ".html", ".css", ".md"}


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("Git operation failed: " + args[0])
    return result.stdout


def include(relative: str) -> bool:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative or not path.parts:
        return False
    if any(part in OMIT_PARTS or part.startswith(".build-staging-") for part in path.parts):
        return False
    if relative.startswith(OMIT_PREFIXES):
        return False
    name = path.name.lower()
    if name.startswith(".env") and name != ".env.example":
        return False
    if name in PRIVATE_NAMES or name.endswith(PRIVATE_SUFFIXES) or name.startswith("~$"):
        return False
    if len(path.parts) == 1:
        return relative in ROOT_FILES or name.startswith(("license", "notice", "copying", "copyright", "authors"))
    return (path.parts[0] in SOURCE_ROOTS
            or relative.startswith(("deploy/fork/", "integration-sources/workloop/"))
            or relative in {"deploy/build_frontend.ps1", "deploy/publish_frontend.ps1"})


def linked(path: Path, root: Path) -> bool:
    for item in (path, *path.parents):
        if item == root:
            break
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            return True
    return False


def selected_files(source: Path) -> list[str]:
    raw = git(source, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    candidates = {item.decode("utf-8") for item in raw.split(b"\0") if item}
    return sorted(relative for relative in candidates
                  if include(relative) and (source / relative).is_file()
                  and not linked(source / relative, source))


def rebrand(relative: str, data: bytes, name: str) -> bytes:
    if relative == "AGENTS.md":
        value = data.decode("utf-8").replace("vAIPlatform", name)
        value += ("\n# PokeDev fork direction\n\n"
                  "- Build on the vAIPlatform control plane. Do not introduce new Workloop dependencies; retain existing ones only while replacing the documented legacy paths.\n"
                  "- Use GitHub for source hosting and the target repository adapter. Existing Gitea code is migration context.\n"
                  "- Keep the PokeDev product name and restored PokeDev assets. Keep backend API namespaces stable unless a migration requires a versioned change.\n"
                  "- Configure credentials and runtime data independently from ADLC. Do not copy its databases, sessions, tokens or local recovery settings.\n")
        return value.encode("utf-8")
    if relative.startswith("adlc-flow/frontend/") and PurePosixPath(relative).suffix in BRAND_SUFFIXES:
        value = data.decode("utf-8")
        value = value.replace("VAIPlatformLogo.svg", "PokeDevLogo.svg")
        value = value.replace("vAIPlatform", name).replace("vAI Platform", name)
        if relative.endswith((".test.ts", ".test.tsx")):
            value = value.replace("vaiplatform", name.lower())
        if relative == "adlc-flow/frontend/package.json":
            body = json.loads(value)
            body["name"] = "pokedev"
            value = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
        elif relative == "adlc-flow/frontend/package-lock.json":
            body = json.loads(value)
            body["name"] = "pokedev"
            if "" in body.get("packages", {}):
                body["packages"][""]["name"] = "pokedev"
            value = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
        return value.encode("utf-8")
    return data


def validate_output(source: Path, output: Path) -> None:
    if output == source or source in output.parents or output in source.parents:
        raise ValueError("The fork must be outside the source repository.")
    if linked(output, Path(output.anchor)):
        raise ValueError("The fork destination must not use symlinks or junctions.")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("The destination must be a new or empty directory.")


def prepare(source: Path, output: Path, name: str, github: str, *, write: bool = False) -> dict:
    source = source.resolve(strict=True)
    # Inspect link components before resolving the requested destination.
    requested = output.absolute()
    if linked(requested, Path(requested.anchor)):
        raise ValueError("The fork destination must not use symlinks or junctions.")
    output = requested.resolve()
    validate_output(source, output)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", github):
        raise ValueError("GitHub repository must use owner/name format.")
    files = selected_files(source)
    info = {"name": name, "files": len(files), "output": str(output), "github_repository": github,
            "source_commit": git(source, "rev-parse", "HEAD").decode().strip(),
            "source_branch": git(source, "branch", "--show-current").decode().strip()}
    if not write:
        return {**info, "written": False}
    old_logo = git(source, "show", "HEAD:adlc-flow/frontend/src/assets/PokeDevLogo.svg")
    if not old_logo.lstrip().startswith(b"<svg"):
        raise ValueError("The original PokeDev logo could not be verified.")
    templates = source / "deploy/fork"
    readme = (templates / "README.fork.md").read_text(encoding="utf-8")
    environment = (templates / "env.example").read_bytes()
    guidance = (templates / "migration.md").read_bytes()
    output.mkdir(parents=True, exist_ok=True)
    inventory = []
    for relative in files:
        if relative == "adlc-flow/frontend/src/assets/VAIPlatformLogo.svg":
            continue
        destination = "docs/upstream-readme.md" if relative == "Readme.md" else relative
        data = (source / relative).read_bytes()
        transformed = rebrand(relative, data, name)
        target = output / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(transformed)
        inventory.append({"source": relative, "path": destination,
                          "source_sha256": hashlib.sha256(data).hexdigest(),
                          "sha256": hashlib.sha256(transformed).hexdigest()})
    for relative in ("adlc-flow/frontend/src/assets/PokeDevLogo.svg", "adlc-flow/frontend/public/favicon.svg"):
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(old_logo)
    (output / "Readme.md").write_text(readme.replace("{{GITHUB_REPOSITORY}}", github), encoding="utf-8")
    (output / ".env.example").write_bytes(environment)
    (output / "docs/fork-preparation.md").write_bytes(guidance)
    ignore = output / ".gitignore"
    with ignore.open("a", encoding="utf-8") as stream:
        stream.write("\n# Independent fork state\n/data/\n/tmp/\n*.sqlite\n*.sqlite3\n*.sqlite3-*\n*.db-*\n*.log\n.fork-local/\n.build-staging-*/\n")
    for entry in inventory:
        entry["sha256"] = hashlib.sha256((output / entry["path"]).read_bytes()).hexdigest()
    provenance = {"schema_version": 1, "product": name, "github_repository": github,
                  "upstream_repository": "https://github.com/VDT-2026/VDT-ADLC.git",
                  "upstream_commit": info["source_commit"], "upstream_branch": info["source_branch"],
                  "snapshot": "current working tree including uncommitted source changes",
                  "history": "new local history; upstream Git objects are not copied",
                  "target_control_plane": "vaiplatform", "workloop_migration": "required",
                  "source_files": len(inventory),
                  "source_manifest_sha256": hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest(),
                  "excluded": ["credentials and private env", "application databases and sessions", "runtime downloads", "dependencies and builds", "reports and demo evidence", "upstream Git history"]}
    (output / "fork-baseline.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "deploy/fork/source-manifest.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "PokeDev.code-workspace").write_text(json.dumps({"folders": [{"path": "."}], "settings": {"python.defaultInterpreterPath": "${workspaceFolder}/adlc-flow/.venv/Scripts/python.exe"}}, indent=2) + "\n", encoding="utf-8")
    git(output, "init", "--initial-branch=codex/pokedev-fork-prep")
    git(output, "config", "core.longpaths", "true")
    git(output, "config", "core.autocrlf", "false")
    git(output, "config", "core.whitespace", "blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol")
    git(output, "remote", "add", "origin", "https://github.com/" + github + ".git")
    git(output, "remote", "add", "upstream", "https://github.com/VDT-2026/VDT-ADLC.git")
    git(output, "config", "remote.pushDefault", "origin")
    return {**info, "written": True, "copied_files": len(inventory), "remote_repository_created": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--name", default="PokeDev")
    parser.add_argument("--github", required=True)
    parser.add_argument("--write", action="store_true", help="Create the local preparation repository; otherwise preview only.")
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output, args.name, args.github, write=args.write), ensure_ascii=False))


if __name__ == "__main__":
    main()
