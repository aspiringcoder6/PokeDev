"""Read a bounded file index from the project's pinned Git tree, never its working tree."""
from pathlib import PurePosixPath
import re

from langflow.adlc.gitea_projects import OMIT, git
from langflow.adlc.live_workflows import safe_path
from langflow.adlc.vai_services import ServiceCheckError


def project_file_index(project):
    commit = project["base_commit"]
    if not re.fullmatch(r"[a-f0-9]{40}(?:[a-f0-9]{24})?", commit):
        raise ServiceCheckError("PROJECT_SOURCE_UNAVAILABLE", 503)
    paths, truncated = [], False
    for entry in git(project["source_path"], "ls-tree", "-rz", commit, raw=True).split("\0"):
        if not entry:
            continue
        metadata, separator, path = entry.partition("\t")
        # Symlinks, submodules, generated files and secret names aren't editable source.
        if not separator or metadata.split()[0] not in {"100644", "100755"} or not safe_path(path):
            continue
        parts = PurePosixPath(path).parts
        if any(part in OMIT or part.startswith(".env") for part in parts) or any(secret in path.lower() for secret in ("credentials", "private-key", "id_rsa", ".pem")):
            continue
        if len(paths) >= 20000:
            truncated = True
            break
        paths.append(path)
    return {"project_id": project["project_id"], "commit": commit, "paths": sorted(paths), "truncated": truncated}
