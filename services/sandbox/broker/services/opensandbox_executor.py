"""Direct OpenSandbox execd execution path (opensandbox provider).

Actions submitted to `/api/v1/agent/execute` are executed directly against the
sandbox's built-in execd agent via the async `opensandbox` SDK — no host-side
runner process and no WebSocket relay. The Docker provider keeps its
in-container go-runner over WS: `agent.py` gates on
`provider.runner_is_in_container` and only routes here when the runner is NOT
in the container.

Action semantics mirror the go-runner (`executor/go-runner/main.go`,
handleAction) plus the extended node-runner actions (findFiles / grep / mkdir
/ runGitCommand), with every file/dir path resolved under /workspace by
`_sandbox_path` (same manifest-aware rule as the broker's `_sync_path`).
"""
import asyncio
import base64
import posixpath
import shlex
import time
from datetime import timedelta
from typing import Any, Awaitable, Callable, Optional

from broker.services.opensandbox_connection import async_connection_config
from broker.state import logger

try:
    from opensandbox.models.execd import RunCommandOpts
    from opensandbox.models.filesystem import DirectoryListEntry, WriteEntry
except ImportError:  # SDK optional at import time (docker provider never routes here)
    RunCommandOpts = None
    DirectoryListEntry = None
    WriteEntry = None

_WORKSPACE_ROOT = "/workspace"

# Error code used when the VFS->sandbox sync_files application fails: agent.py
# keys off it to keep the session's synced manifest untouched (self-healing on
# the next shell command).
SYNC_FAILED_ERROR_CODE = "SYNC_FAILED"

_DEFAULT_COMMAND_TIMEOUT_S = 120.0
_CONNECT_TIMEOUT_S = 10.0


def _shell_quote(value: str) -> str:
    """POSIX single-quote escaping for interpolating text into shell text."""
    return str(value).replace("'", "'\\''")


def _result(
    status: str,
    stdout: str = "",
    stderr: str = "",
    exit_code: Optional[int] = 0,
    error: Optional[dict] = None,
) -> dict:
    """Execution record in the go-runner response shape (durationMs added by execute())."""
    return {
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
        "exitCode": exit_code,
        "error": error,
    }


class OpenSandboxDirectExecutor:
    """Executes broker actions directly against an OpenSandbox sandbox execd.

    Keeps one async `Sandbox` handle per sandbox_id, lazily connected on first
    use. A failed SDK call evicts the cached handle and reconnects exactly once
    before surfacing the error (covers endpoint changes after pause/resume and
    stale cached handles).
    """

    def __init__(self) -> None:
        self._handles: dict[str, Any] = {}
        self._connect_lock = asyncio.Lock()

    async def get_handle(self, sandbox_id: str) -> Any:
        """Return the cached Sandbox handle for sandbox_id, connecting lazily."""
        if sandbox_id in self._handles:
            return self._handles[sandbox_id]
        async with self._connect_lock:
            if sandbox_id not in self._handles:
                self._handles[sandbox_id] = await self._connect(sandbox_id)
        return self._handles[sandbox_id]

    async def evict(self, sandbox_id: str) -> None:
        """Drop (and close) the cached handle for sandbox_id."""
        handle = self._handles.pop(sandbox_id, None)
        if handle is None:
            return
        try:
            await handle.close()
        except Exception as e:
            logger.debug(f"[OpenSandboxExecutor] Error closing evicted handle for '{sandbox_id}': {e}")

    async def execute(
        self,
        session_id: str,
        sandbox_id: str,
        action: dict,
        timeout_s: float,
        sync_files: Optional[dict] = None,
    ) -> dict:
        """Run one broker action against the sandbox execd.

        Returns {status, stdout, stderr, exitCode, durationMs, error} where
        error is None or {"code": str, "message": str}. Never raises: SDK
        failures degrade to {"status": "error", "exitCode": 1}.
        """
        started = time.monotonic()
        try:
            result = await self._execute_inner(sandbox_id, action, timeout_s, sync_files)
        except Exception as e:
            logger.error(
                f"[OpenSandboxExecutor] session '{session_id}' sandbox '{sandbox_id}' failed: {e}"
            )
            result = _result("error", stderr=str(e), exit_code=1)
        result["durationMs"] = int((time.monotonic() - started) * 1000)
        return result

    async def _execute_inner(
        self,
        sandbox_id: str,
        action: dict,
        timeout_s: float,
        sync_files: Optional[dict],
    ) -> dict:
        sync = sync_files if sync_files is not None else action.get("sync_files")
        if isinstance(sync, dict) and (sync.get("changed") or sync.get("deleted")):
            try:
                await self._with_handle(sandbox_id, lambda handle: self._apply_sync(handle, sync))
            except Exception as e:
                logger.warning(
                    f"[OpenSandboxExecutor] sync_files failed for sandbox '{sandbox_id}': {e}"
                )
                return _result(
                    "error",
                    stderr=str(e),
                    exit_code=1,
                    error={
                        "code": SYNC_FAILED_ERROR_CODE,
                        "message": f"Failed to sync project files into the sandbox: {e}",
                    },
                )
        return await self._with_handle(sandbox_id, lambda handle: self._run_action(handle, action, timeout_s))

    async def _with_handle(
        self,
        sandbox_id: str,
        op: Callable[[Any], Awaitable[dict]],
    ) -> dict:
        """Run op(handle); on failure evict + reconnect once and retry op."""
        handle = await self.get_handle(sandbox_id)
        try:
            return await op(handle)
        except Exception as first_err:
            logger.warning(
                f"[OpenSandboxExecutor] cached handle for '{sandbox_id}' failed "
                f"({first_err}); reconnecting once"
            )
            await self.evict(sandbox_id)
            handle = await self.get_handle(sandbox_id)
            return await op(handle)

    async def _connect(self, sandbox_id: str) -> Any:
        if RunCommandOpts is None:
            raise RuntimeError("SANDBOX_PROVIDER=opensandbox requires the opensandbox SDK")
        from opensandbox.sandbox import Sandbox

        return await Sandbox.connect(
            sandbox_id,
            connection_config=async_connection_config(),
            connect_timeout=timedelta(seconds=_CONNECT_TIMEOUT_S),
            skip_health_check=True,
        )

    # ------------------------------------------------------------------
    # Path resolution (go-runner safePath parity + manifest-aware /workspace)
    # ------------------------------------------------------------------

    @staticmethod
    def _sandbox_path(p: str) -> str:
        """Resolve an action path to an absolute in-sandbox path.

        - ""               -> /workspace
        - "/workspace"     -> /workspace
        - "/workspace/..." -> kept as-is (manifest-aware exception, same rule
          as the broker's `_sync_path`: when the project really has a
          top-level 'workspace' folder, VFS paths legitimately carry the prefix)
        - anything else    -> leading slashes stripped, joined under /workspace
        Backslashes are normalized to slashes; "." / ".." segments are folded
        (mirrors go-runner's filepath.Join cleaning).
        """
        norm = (p or "").replace("\\", "/")
        if not norm or norm == _WORKSPACE_ROOT:
            return _WORKSPACE_ROOT
        if norm.startswith(_WORKSPACE_ROOT + "/"):
            return posixpath.normpath(norm)
        return posixpath.normpath(posixpath.join(_WORKSPACE_ROOT, norm.lstrip("/")))

    @staticmethod
    def _command_timeout_s(timeout_s: float) -> float:
        try:
            timeout = float(timeout_s)
        except (TypeError, ValueError):
            return _DEFAULT_COMMAND_TIMEOUT_S
        return timeout if timeout > 0 else _DEFAULT_COMMAND_TIMEOUT_S

    # ------------------------------------------------------------------
    # Action dispatch (go-runner handleAction semantics)
    # ------------------------------------------------------------------

    async def _run_action(self, handle: Any, action: dict, timeout_s: float) -> dict:
        if isinstance(action.get("runShellCommand"), dict):
            return await self._run_shell_command(handle, action["runShellCommand"], timeout_s)
        if isinstance(action.get("runCommand"), dict):
            return await self._run_run_command(handle, action["runCommand"], timeout_s)
        if isinstance(action.get("runReadFile"), dict):
            return await self._run_read_file(handle, action["runReadFile"])
        if isinstance(action.get("runWriteFile"), dict):
            return await self._run_write_file(handle, action["runWriteFile"])
        if isinstance(action.get("writeFiles"), dict):
            return await self._run_write_files(handle, action["writeFiles"])
        if isinstance(action.get("listDirectory"), dict):
            return await self._run_list_directory(handle, action["listDirectory"])
        if isinstance(action.get("mkdir"), dict):
            return await self._run_mkdir(handle, action["mkdir"])
        if isinstance(action.get("findFiles"), dict):
            return await self._run_find_files(handle, action["findFiles"], timeout_s)
        if isinstance(action.get("grep"), dict):
            return await self._run_grep(handle, action["grep"], timeout_s)
        if isinstance(action.get("runGitCommand"), dict):
            return await self._run_git_command(handle, action["runGitCommand"], timeout_s)
        # go-runner parity: every non-request key is reported as unsupported
        # (sync_files was already consumed above but stays listed, like go-runner).
        keys = [k for k in action if k not in ("requestId", "requestID", "request_id")]
        return _result(
            "error",
            stderr="unsupported action keys: " + ",".join(sorted(keys)),
            exit_code=1,
        )

    async def _execute_command(
        self,
        handle: Any,
        command: str | list[str],
        working_directory: str,
        timeout_s: float,
    ) -> dict:
        """Run shell text (or SDK argv list) in the sandbox and normalize the SDK Execution.

        execd reports a server-side kill (command timeout) as a negative exit
        code with error 'signal: killed' (verified empirically) — mapped to the
        broker's COMMAND_TIMEOUT response shape.
        """
        timeout = self._command_timeout_s(timeout_s)
        opts = RunCommandOpts(working_directory=working_directory, timeout=timedelta(seconds=timeout))
        execution = await handle.commands.run(command, opts=opts)
        stdout = "\n".join(msg.text for msg in execution.logs.stdout)
        stderr = "\n".join(msg.text for msg in execution.logs.stderr)
        exit_code = execution.exit_code
        if exit_code is not None and exit_code < 0:
            return _result(
                "timeout",
                exit_code=None,
                error={
                    "code": "COMMAND_TIMEOUT",
                    "message": f"Execution timed out after {int(timeout)} seconds",
                },
            )
        if exit_code is None:
            exit_code = 0 if execution.error is None else 1
        return _result(
            "success" if exit_code == 0 else "error",
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )

    async def _run_shell_command(self, handle: Any, spec: dict, timeout_s: float) -> dict:
        command = spec.get("command", "")
        cwd = self._sandbox_path(spec["cwd"]) if spec.get("cwd") else _WORKSPACE_ROOT
        return await self._execute_command(handle, command, cwd, timeout_s)

    async def _run_run_command(self, handle: Any, spec: dict, timeout_s: float) -> dict:
        """Run one program with argv-style arguments (remote `cmd` verb).

        The SDK's Commands.run also accepts argv lists, but the deployed execd
        build rejects argv-only request bodies (RunCommandRequest.Command is a
        required field — verified against the live server), so the argv is
        joined with POSIX quoting instead: shell metacharacters stay inert,
        keeping the shell-text path injection-safe.
        """
        program = spec.get("program")
        if not program:
            return _result("error", stderr="runCommand requires a 'program'", exit_code=1)
        arguments = spec.get("arguments") or []
        flags = spec.get("flags") or []
        argv = [program] + [str(a) for a in arguments] + [str(f) for f in flags]
        command = shlex.join(argv)
        return await self._execute_command(handle, command, _WORKSPACE_ROOT, timeout_s)

    async def _run_read_file(self, handle: Any, spec: dict) -> dict:
        target = self._sandbox_path(spec.get("filepath", ""))
        if (spec.get("encoding") or "") == "base64":
            raw = await handle.files.read_bytes(target)
            out = base64.b64encode(raw).decode("ascii")
        else:
            out = await handle.files.read_file(target)
        return _result("success", stdout=out)

    async def _run_write_file(self, handle: Any, spec: dict) -> dict:
        target = self._sandbox_path(spec.get("filepath", ""))
        contents = spec.get("contents", "")
        await self._ensure_parent_dir(handle, target)
        await handle.files.write_files([WriteEntry(path=target, data=contents)])
        return _result("success", stdout=f"written {target}")

    async def _run_write_files(self, handle: Any, spec: dict) -> dict:
        errs: list[str] = []
        entries = []
        for item in spec.get("files") or []:
            if not isinstance(item, dict):
                errs.append(f"invalid file entry: {item!r}")
                continue
            path = item.get("filepath") or item.get("path") or ""
            if not path:
                errs.append("file entry missing 'filepath'")
                continue
            target = self._sandbox_path(path)
            try:
                await self._ensure_parent_dir(handle, target)
                entries.append(WriteEntry(path=target, data=item.get("contents", "")))
            except Exception as e:
                errs.append(str(e))
        if errs:
            return _result("error", stderr="\n".join(errs), exit_code=1)
        if entries:
            await handle.files.write_files(entries)
        return _result("success", stdout=f"written {len(entries)} files")

    async def _run_list_directory(self, handle: Any, spec: dict) -> dict:
        target = self._sandbox_path(spec.get("path", ""))
        infos = await handle.files.list_directory(DirectoryListEntry(path=target))
        names = [posixpath.basename(info.path) for info in infos]
        return _result("success", stdout="\n".join(names))

    async def _run_mkdir(self, handle: Any, spec: dict) -> dict:
        raw = spec.get("directory_path") or spec.get("path") or spec.get("filepath") or ""
        target = self._sandbox_path(raw)
        await handle.files.create_directories([WriteEntry(path=target)])
        return _result("success", stdout=f"created {target}")

    async def _run_find_files(self, handle: Any, spec: dict, timeout_s: float) -> dict:
        pattern = str(spec.get("name_pattern") or spec.get("pattern") or "")
        command = f"find {_WORKSPACE_ROOT} -name '{_shell_quote(pattern)}'"
        return await self._execute_command(handle, command, _WORKSPACE_ROOT, timeout_s)

    async def _run_grep(self, handle: Any, spec: dict, timeout_s: float) -> dict:
        pattern = str(spec.get("pattern") or spec.get("keywords") or "")
        directory = spec.get("search_directory") or spec.get("directory") or "."
        target_dir = self._sandbox_path(directory)
        case_flag = " -i" if (spec.get("case_insensitive") or spec.get("ignore_case")) else ""
        command = (
            f"grep -rn{case_flag} -e '{_shell_quote(pattern)}' '{target_dir}'"
        )
        return await self._execute_command(handle, command, _WORKSPACE_ROOT, timeout_s)

    async def _run_git_command(self, handle: Any, spec: dict, timeout_s: float) -> dict:
        parts = ["git", str(spec.get("command") or "")]
        args = spec.get("args") or spec.get("arguments")
        if args:
            parts.append(str(args))
        return await self._execute_command(handle, " ".join(parts).strip(), _WORKSPACE_ROOT, timeout_s)

    # ------------------------------------------------------------------
    # sync_files (VFS -> sandbox delta, go-runner applySync semantics)
    # ------------------------------------------------------------------

    async def _apply_sync(self, handle: Any, sync: dict) -> None:
        deleted = [self._sandbox_path(p) for p in (sync.get("deleted") or [])]
        if deleted:
            await handle.files.delete_files(deleted)
        changed = sync.get("changed") or []
        if not changed:
            return
        entries = []
        for item in changed:
            if not isinstance(item, dict):
                raise ValueError(f"invalid sync entry: {item!r}")
            target = self._sandbox_path(item.get("path", ""))
            raw_b64 = item.get("contentBase64", "")
            data = base64.b64decode(raw_b64) if raw_b64 else b""
            await self._ensure_parent_dir(handle, target)
            entries.append(WriteEntry(path=target, data=data))
        await handle.files.write_files(entries)

    async def _ensure_parent_dir(self, handle: Any, target: str) -> None:
        parent = posixpath.dirname(target)
        if not parent or parent == "/" or parent == _WORKSPACE_ROOT:
            return
        try:
            await handle.files.create_directories([WriteEntry(path=parent)])
        except Exception as e:
            if "already exists" not in str(e).lower():
                raise


# Module-level singleton accessor
_executor: Optional[OpenSandboxDirectExecutor] = None


def get_executor() -> OpenSandboxDirectExecutor:
    global _executor
    if _executor is None:
        _executor = OpenSandboxDirectExecutor()
    return _executor
