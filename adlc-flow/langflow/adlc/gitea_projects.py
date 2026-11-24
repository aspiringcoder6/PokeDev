"""Gitea projects with server-side credentials and immutable Git source reads."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import subprocess

import httpx
from dotenv import dotenv_values

from langflow.adlc.vai_services import ServiceCheckError

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "adlc-flow/data/live-projects"
OMIT = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".angular", ".next", "target"}


def configuration():
    values = {**dotenv_values(ROOT / ".env.vai-platform.local"), **os.environ}
    base = values.get("VAI_GITEA_URL", "http://10.0.10.195:3000").rstrip("/")
    parsed = httpx.URL(base)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or parsed.query:
        raise ServiceCheckError("GITEA_CONFIGURATION_INVALID", 503)
    token = values.get("VAI_GITEA_TOKEN")
    if not token:
        raise ServiceCheckError("GITEA_NOT_CONFIGURED", 503)
    return base, values.get("VAI_GITEA_USER", "admin"), token


class Gitea:
    async def request(self, method, path, body=None):
        base, _, token = configuration()
        try:
            async with httpx.AsyncClient(base_url=base, trust_env=False, timeout=25, follow_redirects=False) as client:
                response = await client.request(method, "/api/v1" + path, json=body, headers={"Authorization": "token " + token})
            if response.status_code in {401, 403}:
                raise ServiceCheckError("GITEA_ACCESS_DENIED", 503)
            if response.status_code == 404:
                raise ServiceCheckError("GITEA_REPOSITORY_NOT_FOUND", 404)
            if response.status_code in {409, 422}:
                if "/pulls" in path:
                    raise ServiceCheckError("GITEA_CHANGE_REJECTED")
                raise ServiceCheckError("GITEA_REPOSITORY_NAME_UNAVAILABLE")
            if response.status_code == 405 and path.endswith("/merge"):
                raise ServiceCheckError("GITEA_CHANGE_REJECTED")
            if not response.is_success:
                raise ServiceCheckError("GITEA_REQUEST_FAILED", 503)
            return response.json() if response.content else None
        except httpx.HTTPError:
            raise ServiceCheckError("GITEA_UNAVAILABLE", 503) from None

    @staticmethod
    def public(repo):
        return {key: repo.get(key) for key in ("id", "name", "full_name", "description", "html_url", "default_branch", "empty", "private")}

    async def repositories(self):
        found = []
        for page in range(1, 21):
            rows = await self.request("GET", f"/user/repos?limit=50&page={page}")
            found.extend(self.public(repo) for repo in rows if not repo.get("archived"))
            if len(rows) < 50:
                break
        return found

    async def repository(self, identity):
        return await self.request("GET", "/repositories/" + str(int(identity)))

    async def create(self, name, description):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,79}", name):
            raise ServiceCheckError("GITEA_REPOSITORY_NAME_INVALID", 422)
        return await self.request("POST", "/user/repos", {"name": name, "description": description[:500], "private": True, "auto_init": True, "default_branch": "main"})


def git(folder, *args, network=False, timeout=120, raw=False):
    env = {k: v for k, v in os.environ.items() if k.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    if network:
        _, user, token = configuration()
        auth = base64.b64encode((user + ":" + token).encode()).decode()
        env.update(GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="http.extraHeader", GIT_CONFIG_VALUE_0="Authorization: Basic " + auth,
                   GIT_CONFIG_KEY_1="http.proxy", GIT_CONFIG_VALUE_1="")
    command = ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false", "-c", "core.longpaths=true", "-c", "core.autocrlf=false", "-c", "credential.helper=", "-c", "http.lowSpeedLimit=1", "-c", "http.lowSpeedTime=30", "-c", "protocol.ext.allow=never", "-c", "http.followRedirects=false", "-C", str(folder), *map(str, args)]
    try:
        result, output = bounded_process(command, env, timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise ServiceCheckError("PROJECT_GIT_UNAVAILABLE", 503) from None
    if result:
        raise ServiceCheckError("PROJECT_GIT_OPERATION_FAILED", 503)
    text = output.decode("utf8", errors="replace")
    return text if raw else text.strip()


def prepare_candidate(source_path, revision, candidate):
    """Rebuild a candidate from a frozen commit, including cache-only objects."""
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", revision):
        raise ServiceCheckError("PROJECT_SOURCE_REVISION_INVALID", 503)
    candidate = Path(candidate)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    git(candidate.parent, "clone", "--no-local", "--no-checkout", "--", source_path, str(candidate))
    # Source caches keep their checked-out branch frozen while later fetches
    # populate FETCH_HEAD. A transport clone includes advertised branches, so
    # it can omit the newer reviewed object. Fetch that exact object explicitly.
    git(candidate, "fetch", "--no-tags", "--", source_path, revision)
    observed = git(candidate, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
    if observed != revision:
        raise ServiceCheckError("PROJECT_SOURCE_REVISION_MISMATCH", 503)
    git(candidate, "checkout", "--detach", observed)


def bounded_process(command, env, timeout):
    """Terminate the process tree on timeout; child Git helpers must not retain pipes."""
    import psutil
    child = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        stdout, _ = child.communicate(timeout=timeout)
        return child.returncode, stdout
    except subprocess.TimeoutExpired:
        try:
            descendants = psutil.Process(child.pid).children(recursive=True)
        except psutil.Error:
            descendants = []
        for process in reversed(descendants):
            try:
                process.kill()
            except psutil.Error:
                pass
        child.kill()
        try:
            child.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            child.stdout.close(); child.stderr.close()
        raise


def checkout(owner, project_id, repo, *, materialize=True):
    base, _, _ = configuration()
    full_name = repo.get("full_name", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise ServiceCheckError("GITEA_REPOSITORY_INVALID", 422)
    folder = DATA / owner / project_id
    if not folder.exists():
        folder.parent.mkdir(parents=True, exist_ok=True)
        git(folder.parent, "clone", "--no-checkout", "--", base + "/" + full_name + ".git", str(folder), network=True)
    branch = repo.get("default_branch") or "main"
    git(folder, "fetch", "origin", "--", branch, network=True)
    revision = git(folder, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
    # This cache is only read by runs; candidates live in separate per-run clones.
    if materialize and not (folder / ".pokedev-source.json").exists():
        git(folder, "checkout", "--detach", revision)
    (folder / ".pokedev-source.json").write_text(json.dumps({"repository_id": repo["id"], "commit": revision}), encoding="utf8")
    return str(folder), revision


def source_files(folder, commit, *, required_paths=()):
    """Keep planned edits in context before spending the optional source budget."""
    files, tree, total = {}, [], 0
    required = set(required_paths)
    for path in git(folder, "ls-tree", "-rz", "--name-only", commit, raw=True).split("\0"):
        if not path:
            continue
        parts = Path(path).parts
        if any(p in OMIT or p.startswith(".env") for p in parts) or any(x in path.lower() for x in ("credentials", "private-key", "id_rsa", ".pem")):
            continue
        tree.append(path)
        if len(tree) > 20000:
            raise ServiceCheckError("PROJECT_SOURCE_TOO_LARGE", 422)
    cached, references = {}, set()
    for path in tree:
        if path not in required or not path.endswith(".java"):
            continue
        size = int(git(folder, "cat-file", "-s", commit + ":" + path))
        if size > 160000:
            raise ServiceCheckError("PROJECT_REQUIRED_SOURCE_TOO_LARGE", 422)
        value = git(folder, "show", commit + ":" + path, raw=True)
        cached[path] = (size, value)
        references.update(re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", value))
    for path in sorted(tree, key=lambda item: (item not in required, Path(item).stem not in references)):
        # File contents are context; binary assets are copied only into the build archive.
        if Path(path).suffix.lower() not in {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss", ".json", ".md", ".txt", ".yml", ".yaml", ".toml", ".xml", ".java", ".go", ".rs", ".cs", ".sh", ".properties"}:
            continue
        size = cached[path][0] if path in cached else int(git(folder, "cat-file", "-s", commit + ":" + path))
        if size > (160000 if path in required else 100000) or total + size > 1200000:
            if path in required:
                raise ServiceCheckError("PROJECT_REQUIRED_SOURCE_TOO_LARGE", 422)
            continue
        value = cached[path][1] if path in cached else git(folder, "show", commit + ":" + path, raw=True)
        if "\0" not in value:
            files[path] = value
            total += size
    # A new path need not exist yet. Existing granted paths must have their
    # exact baseline, including text resource files, before an agent can edit.
    if (required & set(tree)) - set(files):
        raise ServiceCheckError("PROJECT_REQUIRED_SOURCE_UNAVAILABLE", 422)
    return files, tree
