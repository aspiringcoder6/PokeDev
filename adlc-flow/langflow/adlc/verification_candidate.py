"""Reconstruct a bounded JSON candidate from the archived patch and pinned base.

No project code, Git hooks, host-selected paths or remote URLs are executed.
"""

# ruff: noqa: EM101, TRY003 - fixed, secret-safe validation codes/messages.

import json
import re

from langflow.adlc.contract_execution import safe_relative_path
from langflow.adlc.local_projects import LOCAL_PROJECT_KEY, git_at, snapshot_path
from langflow.adlc.verification_models import MAX_CANDIDATE_BYTES, CandidateReference, VerificationError, canonical

MAX_DEPTH = 16


def strict_json(text: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def depth(value, level=0):
        if level > MAX_DEPTH:
            raise ValueError("JSON nesting is too deep")
        if isinstance(value, dict):
            for item in value.values():
                depth(item, level + 1)
        elif isinstance(value, list):
            for item in value:
                depth(item, level + 1)

    if len(text.encode("utf-8")) > MAX_CANDIDATE_BYTES:
        raise VerificationError("VERIFICATION_CANDIDATE_TOO_LARGE", 413)
    value = json.loads(text, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    depth(value)
    return value


def apply_file_patch(base: str, patch: str, file: str) -> str:
    lines = patch.splitlines()
    # Only the collector's literal, single-file textual Git diff is supported.
    if not lines or lines[0] != f"diff --git a/{file} b/{file}" or "GIT binary patch" in lines:
        raise VerificationError("VERIFICATION_PATCH_UNSUPPORTED", 422)
    before = base.splitlines()
    output, cursor, index, hunks = [], 0, 0, 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("diff --git ") and index:
            raise VerificationError("VERIFICATION_PATCH_UNSUPPORTED", 422)
        if line.startswith("--- ") and line not in {f"--- a/{file}", "--- /dev/null"}:
            raise VerificationError("VERIFICATION_PATCH_UNSUPPORTED", 422)
        if line.startswith("+++ ") and line != f"+++ b/{file}":
            raise VerificationError("VERIFICATION_PATCH_UNSUPPORTED", 422)
        match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if not match:
            index += 1
            continue
        hunks += 1
        old_start, old_count, new_start, new_count = (
            int(match[1]),
            int(match[2] or 1),
            int(match[3]),
            int(match[4] or 1),
        )
        target = old_start - 1 if old_count else old_start
        if target < cursor or target > len(before):
            raise VerificationError("VERIFICATION_PATCH_BASE_MISMATCH")
        output.extend(before[cursor:target])
        if len(output) != (new_start - 1 if new_count else new_start):
            raise VerificationError("VERIFICATION_PATCH_BASE_MISMATCH")
        cursor, old_used, new_used = target, 0, 0
        index += 1
        while index < len(lines) and not lines[index].startswith("@@ "):
            part = lines[index]
            index += 1
            if part == "\\ No newline at end of file":
                continue
            if not part or part[0] not in " +-":
                raise VerificationError("VERIFICATION_PATCH_UNSUPPORTED", 422)
            if part[0] in " -":
                if cursor >= len(before) or before[cursor] != part[1:]:
                    raise VerificationError("VERIFICATION_PATCH_BASE_MISMATCH")
                cursor += 1
                old_used += 1
            if part[0] in " +":
                output.append(part[1:])
                new_used += 1
        if (old_used, new_used) != (old_count, new_count):
            raise VerificationError("VERIFICATION_PATCH_BASE_MISMATCH")
    if not hunks:
        raise VerificationError("VERIFICATION_PATCH_UNSUPPORTED", 422)
    output.extend(before[cursor:])
    return "\n".join(output)


def freeze_candidate(task, snapshot, file: str):
    import hashlib

    if not safe_relative_path(file) or not file.endswith(".json") or re.search(r"[\s\"*?\[\]]", file):
        raise VerificationError("VERIFICATION_FILE_NOT_ALLOWED", 422)
    if not task.request or snapshot.artifact.attempt_id != task.current_attempt_id:
        raise VerificationError("VERIFICATION_CANDIDATE_STALE")
    reference = task.request.context.get(LOCAL_PROJECT_KEY)
    if not isinstance(reference, dict) or snapshot.base_commit != reference.get("base_commit"):
        raise VerificationError("VERIFICATION_PINNED_LOCAL_PROJECT_REQUIRED", 422)
    repository = snapshot_path(reference)
    if repository.is_symlink() or git_at(repository, "rev-parse", "HEAD^{commit}") != snapshot.base_commit:
        raise VerificationError("VERIFICATION_SOURCE_MISMATCH")
    selected = next((item for item in snapshot.files if item.file == file), None)
    if selected is None:
        raise VerificationError("VERIFICATION_CHANGED_JSON_REQUIRED", 422)
    tree = git_at(repository, "ls-tree", snapshot.base_commit, "--", file)
    base = ""
    if tree:
        if not tree.startswith("100644 blob ") or tree.partition("\t")[2] != file:
            raise VerificationError("VERIFICATION_FILE_NOT_ALLOWED", 422)
        blob = tree.split()[2]
        if int(git_at(repository, "cat-file", "-s", blob)) > MAX_CANDIDATE_BYTES:
            raise VerificationError("VERIFICATION_CANDIDATE_TOO_LARGE", 413)
        base = git_at(repository, "show", f"{snapshot.base_commit}:{file}")
    elif "--- /dev/null" not in selected.patch.splitlines():
        raise VerificationError("VERIFICATION_SOURCE_MISMATCH")
    value = strict_json(apply_file_patch(base, selected.patch, file))
    content = canonical(value).decode("utf-8")
    candidate = CandidateReference(
        source_task_id=task.id,
        source_attempt_id=task.current_attempt_id,
        source_session_id=task.result.metadata.get("harness_session_id", "") if task.result else "",
        artifact_id=snapshot.artifact.artifact_id,
        artifact_digest="sha256:" + snapshot.artifact.checksum.value,
        base_commit=snapshot.base_commit,
        project_id=reference["project_id"],
        source_ref=reference["source_ref"],
        file=file,
        content_digest="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
    )
    return candidate, content
