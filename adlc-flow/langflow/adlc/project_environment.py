"""Versioned build environments and deterministic archives for project runs."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import io
import json
from pathlib import Path
import re
import stat
from uuid import UUID, uuid4, uuid5
import zipfile

from langflow.adlc.gitea_projects import DATA, Gitea, OMIT, checkout, git, prepare_candidate
from langflow.adlc.live_workflows import digest, safe_path
from langflow.adlc.vai_services import ServiceCheckError, now

COMMAND_FIELDS = ("setup", "tests", "build")
DEFAULT_PROFILE = {
    "name": "Môi trường dự án",
    "working_directory": ".",
    "base": None,
    "overlays": [],
    "setup": [],
    "tests": [],
    "build": [],
    "preview": None,
}


def directory_path(value):
    return value == "." or safe_path(value)


def public_environment(value):
    result = deepcopy(value)
    if result and result.get("profile", {}).get("base"):
        result["profile"]["base"].pop("source_path", None)
    return result


def validate_profile(profile):
    if not isinstance(profile, dict) or set(profile) - set(DEFAULT_PROFILE):
        raise ServiceCheckError("LIVE_ENVIRONMENT_INVALID", 422)
    value = {**deepcopy(DEFAULT_PROFILE), **deepcopy(profile)}
    if (
        not isinstance(value["name"], str)
        or not 1 <= len(value["name"].strip()) <= 120
        or not directory_path(value["working_directory"])
    ):
        raise ServiceCheckError("LIVE_ENVIRONMENT_INVALID", 422)
    value["name"] = value["name"].strip()
    for field in COMMAND_FIELDS:
        commands = value[field]
        if not isinstance(commands, list) or len(commands) > 6:
            raise ServiceCheckError("LIVE_ENVIRONMENT_COMMAND_INVALID", 422)
        for command in commands:
            if not isinstance(command, dict) or set(command) - {"label", "argv", "timeout"}:
                raise ServiceCheckError("LIVE_ENVIRONMENT_COMMAND_INVALID", 422)
            argv = command.get("argv")
            timeout = command.get("timeout", 180)
            if (
                not isinstance(command.get("label"), str)
                or not 1 <= len(command["label"]) <= 200
                or not isinstance(argv, list)
                or not 1 <= len(argv) <= 35
                or any(not isinstance(a, str) or not a or len(a) > 500 or "\0" in a for a in argv)
                or type(timeout) is not int
                or not 5 <= timeout <= 600
            ):
                raise ServiceCheckError("LIVE_ENVIRONMENT_COMMAND_INVALID", 422)
    if not value["tests"] or sum(len(value[k]) for k in COMMAND_FIELDS) > 8:
        raise ServiceCheckError("LIVE_ENVIRONMENT_TESTS_REQUIRED", 422)
    base, overlays = value["base"], value["overlays"]
    if base is not None and (
        not isinstance(base, dict)
        or set(base) - {"repository_id", "commit", "repository", "source_path"}
        or type(base.get("repository_id")) is not int
        or base["repository_id"] <= 0
        or (
            base.get("commit") is not None
            and (
                not isinstance(base["commit"], str)
                or base["commit"]
                and not re.fullmatch(r"[a-f0-9]{40}(?:[a-f0-9]{24})?", base["commit"])
            )
        )
    ):
        raise ServiceCheckError("LIVE_ENVIRONMENT_BASE_INVALID", 422)
    if not isinstance(overlays, list) or len(overlays) > 8 or (overlays and not base):
        raise ServiceCheckError("LIVE_ENVIRONMENT_MAPPING_INVALID", 422)
    sources, targets = [], []
    for mapping in overlays:
        if (
            not isinstance(mapping, dict)
            or set(mapping) != {"source", "target"}
            or not directory_path(mapping.get("source"))
            or not safe_path(mapping.get("target"))
        ):
            raise ServiceCheckError("LIVE_ENVIRONMENT_MAPPING_INVALID", 422)
        if mapping["source"] == "." and len(overlays) != 1:
            raise ServiceCheckError("LIVE_ENVIRONMENT_MAPPING_INVALID", 422)
        for old, target in ((sources, mapping["source"]), (targets, mapping["target"])):
            if any(target == p or target.startswith(p + "/") or p.startswith(target + "/") for p in old):
                raise ServiceCheckError("LIVE_ENVIRONMENT_MAPPING_INVALID", 422)
            old.append(target)
    preview = value["preview"]
    if preview is not None:
        if (
            not isinstance(preview, dict)
            or set(preview) - {"path", "argv"}
            or bool(preview.get("argv")) == bool(preview.get("path"))
        ):
            raise ServiceCheckError("LIVE_ENVIRONMENT_PREVIEW_INVALID", 422)
        if preview.get("path") and not directory_path(preview["path"]):
            raise ServiceCheckError("LIVE_ENVIRONMENT_PREVIEW_INVALID", 422)
        if preview.get("argv") and (
            not isinstance(preview["argv"], list)
            or not 1 <= len(preview["argv"]) <= 35
            or any(not isinstance(a, str) or not a or len(a) > 500 or "\0" in a for a in preview["argv"])
        ):
            raise ServiceCheckError("LIVE_ENVIRONMENT_PREVIEW_INVALID", 422)
    return value


def workspace_path(path, environment):
    for mapping in (environment or {}).get("profile", {}).get("overlays", []):
        source, target = mapping["source"], mapping["target"]
        if source == ".":
            return target + "/" + path
        if path == source or path.startswith(source + "/"):
            return target + path[len(source) :]
    return path


def environment_commands(environment):
    """The existing Sandbox protocol runs argv at root; this shim changes cwd without a shell."""
    profile = environment["profile"]
    commands = [deepcopy(command) for field in COMMAND_FIELDS for command in profile[field]]
    cwd = profile["working_directory"]
    if cwd != ".":
        shim = "import os,sys;os.chdir(sys.argv[1]);os.execvp(sys.argv[2],sys.argv[2:])"
        commands = [{**command, "argv": ["python", "-c", shim, cwd, *command["argv"]]} for command in commands]
    return commands


def environment_preview(environment):
    profile = environment["profile"]
    preview, cwd = deepcopy(profile["preview"]), profile["working_directory"]
    if not preview or cwd == ".":
        return preview
    if preview.get("path"):
        preview["path"] = cwd if preview["path"] == "." else cwd + "/" + preview["path"]
    else:
        preview["argv"] = [
            "python",
            "-c",
            "import os,sys;os.chdir(sys.argv[1]);os.execvp(sys.argv[2],sys.argv[2:])",
            cwd,
            *preview["argv"],
        ]
    return preview


def apply_environment(plan, environment):
    from langflow.adlc.live_workflows import validate_plan

    if not environment:
        return validate_plan(deepcopy(plan))
    value = deepcopy(plan)
    value.update(
        commands=environment_commands(environment),
        preview=environment_preview(environment),
        environment_digest=environment["digest"],
    )
    if not value["preview"]:
        value["browser_checks"] = []
    return validate_plan(value)


def archive_sources(candidate, primary_paths, environment, output):
    """Only immutable Git base bytes and the run's scoped candidate enter the Sandbox."""
    entries, origins = {}, {}
    base = (environment or {}).get("profile", {}).get("base")
    if base:
        cache = Path(base["source_path"])
        base_zip = Path(output).with_suffix(".base.zip")
        git(cache, "archive", "--format=zip", "--output=" + str(base_zip), base["commit"])
        expanded = 0
        with zipfile.ZipFile(base_zip) as archive:
            for item in archive.infolist():
                if item.is_dir() or not safe_path(item.filename) or any(p in OMIT for p in Path(item.filename).parts):
                    continue
                if stat.S_ISLNK(item.external_attr >> 16) or item.file_size > 16000000:
                    raise ServiceCheckError("LIVE_ENVIRONMENT_SOURCE_INVALID")
                expanded += item.file_size
                if expanded > 150000000 or len(entries) >= 20000:
                    raise ServiceCheckError("LIVE_SOURCE_ARCHIVE_LIMIT")
                entries[item.filename] = archive.read(item)
        # Replacing a mapped directory also removes files deleted from the primary module.
        for mapping in environment["profile"]["overlays"]:
            for path in list(entries):
                if path == mapping["target"] or path.startswith(mapping["target"] + "/"):
                    entries.pop(path)
    for path in sorted(set(primary_paths)):
        if not safe_path(path) or any(p in OMIT for p in Path(path).parts):
            continue
        target = workspace_path(path, environment)
        if target in origins and origins[target] != path:
            raise ServiceCheckError("LIVE_ENVIRONMENT_MAPPING_COLLISION")
        origins[target] = path
        file = Path(candidate) / path
        if not file.exists():
            entries.pop(target, None)
            continue
        if (
            not file.is_file()
            or any(p.is_symlink() for p in [file, *file.parents] if p != Path(candidate).parent)
            or file.stat().st_size > 16000000
        ):
            raise ServiceCheckError("LIVE_SOURCE_FILE_LIMIT")
        entries[target] = file.read_bytes()
    if len(entries) > 20000 or sum(map(len, entries.values())) > 150000000:
        raise ServiceCheckError("LIVE_SOURCE_ARCHIVE_LIMIT")
    cwd = (environment or {}).get("profile", {}).get("working_directory", ".")
    if cwd != "." and not any(p.startswith(cwd + "/") for p in entries):
        raise ServiceCheckError("LIVE_ENVIRONMENT_DIRECTORY_MISSING")
    if environment:
        for mapping in environment["profile"]["overlays"]:
            if not (mapping["source"] == "." and primary_paths) and not any(
                p == mapping["source"] or p.startswith(mapping["source"] + "/") for p in primary_paths
            ):
                raise ServiceCheckError("LIVE_ENVIRONMENT_SOURCE_MISSING")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, body in sorted(entries.items()):
            item = zipfile.ZipInfo(path, date_time=(2020, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, body)
    raw = Path(output).read_bytes()
    if len(raw) > 60000000:
        raise ServiceCheckError("LIVE_SOURCE_ARCHIVE_LIMIT")
    return raw


class ProjectEnvironment:
    def __init__(self, live, gitea=None):
        self.live, self.gitea = live, gitea or Gitea()
        self.tasks = {}
        with live.store.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS project_environments(project TEXT PRIMARY KEY, owner TEXT, payload TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS environment_checks(id TEXT PRIMARY KEY, owner TEXT, project TEXT, payload TEXT)"
            )

    def read(self, owner, project):
        self.live.store.project(owner, project)
        with self.live.store.db() as db:
            row = db.execute(
                "SELECT payload FROM project_environments WHERE owner=? AND project=?", (owner, project)
            ).fetchone()
        return (
            json.loads(row[0])
            if row
            else {"project_id": project, "revision": 0, "digest": None, "profile": deepcopy(DEFAULT_PROFILE)}
        )

    async def save(self, owner, project, revision, profile):
        self.live.store.project(owner, project)
        # Clients may only select a repository; private cache paths come from the server.
        if (
            isinstance(profile, dict)
            and isinstance(profile.get("base"), dict)
            and set(profile["base"]) - {"repository_id", "commit"}
        ):
            raise ServiceCheckError("LIVE_ENVIRONMENT_BASE_INVALID", 422)
        value = validate_profile(profile)
        if value["base"]:
            repo = await self.gitea.repository(value["base"]["repository_id"])
            cache, head = await asyncio.to_thread(
                checkout, owner, project + "-environment-" + str(repo["id"]), repo, materialize=False
            )
            commit = value["base"].get("commit") or head
            if await asyncio.to_thread(git, cache, "rev-parse", "--verify", commit + "^{commit}") != commit:
                raise ServiceCheckError("LIVE_ENVIRONMENT_BASE_INVALID", 422)
            value["base"] = {
                "repository_id": repo["id"],
                "repository": repo["full_name"],
                "commit": commit,
                "source_path": cache,
            }
        public = public_environment({"profile": value})["profile"]
        with self.live.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT owner,payload FROM project_environments WHERE project=?", (project,)).fetchone()
            old = json.loads(row[1]) if row else {"revision": 0}
            if (row and row[0] != owner) or old["revision"] != revision:
                raise ServiceCheckError("LIVE_ENVIRONMENT_CHANGED")
            result = {
                "project_id": project,
                "revision": revision + 1,
                "profile": value,
                "digest": digest(public),
                "updated_at": now(),
            }
            db.execute(
                "INSERT OR REPLACE INTO project_environments VALUES(?,?,?)",
                (project, owner, json.dumps(result, ensure_ascii=False)),
            )
        return public_environment(result)

    def freeze(self, owner, project):
        value = self.read(owner, project)
        return deepcopy(value) if value["revision"] else None

    def latest_check(self, owner, project):
        self.live.store.project(owner, project)
        with self.live.store.db() as db:
            row = db.execute(
                "SELECT payload FROM environment_checks WHERE owner=? AND project=? ORDER BY rowid DESC LIMIT 1",
                (owner, project),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def check_read(self, owner, project, identity):
        self.live.store.project(owner, project)
        with self.live.store.db() as db:
            row = db.execute(
                "SELECT payload FROM environment_checks WHERE id=? AND owner=? AND project=?",
                (identity, owner, project),
            ).fetchone()
        if not row:
            raise ServiceCheckError("LIVE_ENVIRONMENT_CHECK_NOT_FOUND", 404)
        return json.loads(row[0])

    def check_update(self, value):
        with self.live.store.db() as db:
            db.execute(
                "UPDATE environment_checks SET payload=? WHERE id=?",
                (json.dumps(value, ensure_ascii=False), value["check_id"]),
            )
        return value

    async def begin_check(self, owner, project, identity, expected_digest):
        environment = self.freeze(owner, project)
        if not environment or environment["digest"] != expected_digest:
            raise ServiceCheckError("LIVE_ENVIRONMENT_CHANGED")
        with self.live.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT owner,project,payload FROM environment_checks WHERE id=?", (identity,)).fetchone()
            if old:
                row = json.loads(old[2])
                if old[:2] != (owner, project) or row["environment_digest"] != expected_digest:
                    raise ServiceCheckError("LIVE_ENVIRONMENT_CHANGED")
            else:
                row = {
                    "check_id": identity,
                    "project_id": project,
                    "environment_digest": expected_digest,
                    "state": "PREPARING",
                    "created_at": now(),
                }
                db.execute(
                    "INSERT INTO environment_checks VALUES(?,?,?,?)", (identity, owner, project, json.dumps(row))
                )
        if row["state"] == "PREPARING" and identity not in self.tasks:
            self.tasks[identity] = asyncio.create_task(self.prepare_check(owner, project, row, environment))
            self.tasks[identity].add_done_callback(lambda _: self.tasks.pop(identity, None))
        return row

    async def prepare_check(self, owner, project, row, environment):
        try:
            project_row = self.live.store.project(owner, project)
            repo = await self.gitea.repository(project_row["repository_id"])
            cache, head = await asyncio.to_thread(checkout, owner, project, repo)
            commit = row.get("base_commit") or head
            row["base_commit"] = commit
            self.check_update(row)
            folder = DATA / "environment-checks" / row["check_id"]
            folder.mkdir(parents=True, exist_ok=True)
            candidate = folder / "source"
            if not candidate.exists():
                await asyncio.to_thread(prepare_candidate, cache, commit, candidate)
            paths = git(candidate, "ls-files", "-z", raw=True).strip("\0").split("\0")
            raw = await asyncio.to_thread(archive_sources, candidate, paths, environment, folder / "source.zip")
            import base64
            import hashlib
            from langflow.adlc.vai_services import PlatformClient

            binding = {
                "job_id": row["check_id"],
                "scope_id": digest([owner, project, "environment"]),
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "plan_digest": digest([environment["digest"], commit]),
            }
            row.update(state="RUNNING", base_commit=commit, binding=binding)
            self.check_update(row)  # Persist the identity before submitting the idempotent Sandbox command.
            reply = await PlatformClient().request(
                "POST",
                "/api/v1/pokedev-services/projects/jobs",
                {
                    **binding,
                    "archive_base64": base64.b64encode(raw).decode(),
                    "commands": environment_commands(environment),
                    "protected_paths": [],
                    "preview": None,
                    "browser_checks": [],
                },
            )
            self.check_update({**row, "state": reply["state"], "receipt": reply})
        except Exception as exc:
            self.check_update(
                {
                    **row,
                    "state": "UNCONFIRMED" if row.get("binding") else "FAILED",
                    "error_code": getattr(exc, "code", "LIVE_ENVIRONMENT_CHECK_FAILED"),
                }
            )

    async def refresh_check(self, owner, project, identity):
        row = self.check_read(owner, project, identity)
        if row.get("binding") and row["state"] in {"RUNNING", "UNCONFIRMED"}:
            from langflow.adlc.vai_services import PlatformClient

            binding = row["binding"]
            reply = await PlatformClient().request(
                "GET", "/api/v1/pokedev-services/projects/jobs/" + identity + "?scope_id=" + binding["scope_id"]
            )
            if any(reply.get(k) != v for k, v in binding.items()):
                raise ServiceCheckError("LIVE_SANDBOX_RECEIPT_MISMATCH")
            row.update(state=reply["state"], receipt=reply, error_code=reply.get("error_code"))
            self.check_update(row)
        return row

    async def stop(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
