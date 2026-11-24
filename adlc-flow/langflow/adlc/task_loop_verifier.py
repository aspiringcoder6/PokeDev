"""Run registered behavioral checks against a reconstructed candidate."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from langflow.adlc.task_loop_live_models import LiveLoopEvidence, LiveLoopVerification
from langflow.adlc.task_loop_process import VerificationProcessJob
from langflow.adlc.task_loop_unittest_runner import RESULT_MARKER

if TYPE_CHECKING:
    from uuid import UUID

    from langflow.adlc.task_loop_live_models import LiveLoopCandidate, LiveLoopSpec
    from langflow.adlc.task_loop_workspace import TaskLoopWorkspace

OUTPUT_LIMIT = 8192


async def _stop_process(process, job: VerificationProcessJob | None = None) -> None:
    if job is not None and os.name == "nt":
        if process.returncode is None:
            job.terminate()
        else:
            job.close()
    elif os.name == "nt" and process.returncode is None:
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
    elif os.name != "nt":
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    if process.returncode is None:
        process.kill()
    await process.wait()


async def _bounded_output(stream) -> str:
    retained = bytearray()
    while chunk := await stream.read(4096):
        retained.extend(chunk)
        if len(retained) > OUTPUT_LIMIT:
            del retained[:-OUTPUT_LIMIT]
    return bytes(retained).decode("utf-8", errors="replace")[:OUTPUT_LIMIT]


async def _wait_for_exit(process) -> None:
    # asyncio's Process.wait() can also wait on pipes inherited by a descendant.
    while process.returncode is None:  # noqa: ASYNC110 - observe actual OS exit before closing inherited pipes.
        await asyncio.sleep(0.01)


class TaskLoopVerifier:
    def __init__(self, workspace: TaskLoopWorkspace) -> None:
        self.workspace = workspace

    async def verify(self, attempt_id: UUID, spec: LiveLoopSpec, candidate: LiveLoopCandidate) -> LiveLoopVerification:
        directory = await self.workspace.create(attempt_id, "verify", candidate)
        try:
            checks = []
            for command in spec.verification_commands:
                path = self.workspace.file_path(directory, command.test_path)
                relative = Path(command.test_path)
                test_digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                argv = (
                    sys.executable,
                    "-I",
                    "-B",
                    str(Path(__file__).with_name("task_loop_unittest_runner.py")),
                    relative.as_posix(),
                )
                environment = {
                    name: os.environ[name]
                    for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
                    if name in os.environ
                }
                environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf-8")
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=directory,
                    env=environment,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=os.name != "nt",
                )
                try:
                    job = VerificationProcessJob(process.pid)
                except OSError:
                    await _stop_process(process)
                    raise
                stdout_task = asyncio.create_task(_bounded_output(process.stdout))
                stderr_task = asyncio.create_task(_bounded_output(process.stderr))
                timed_out = False
                try:
                    await asyncio.wait_for(_wait_for_exit(process), command.timeout_ms / 1000)
                except TimeoutError:
                    timed_out = True
                    await _stop_process(process, job)
                except asyncio.CancelledError:
                    await _stop_process(process, job)
                    await asyncio.gather(stdout_task, stderr_task)
                    raise
                finally:
                    # A test may finish while a child still holds its stdout/stderr pipes.
                    await _stop_process(process, job)
                stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
                report = {}
                for line in stdout.splitlines():
                    if line.startswith(RESULT_MARKER):
                        try:
                            report = json.loads(line[len(RESULT_MARKER) :])
                        except json.JSONDecodeError:
                            report = {}
                executed = report.get("executed_tests", 0)
                if not isinstance(executed, int) or isinstance(executed, bool) or executed < 0:
                    executed = 0
                checks.append(
                    LiveLoopEvidence(
                        check_id=command.check_id,
                        argv=argv,
                        test_digest=test_digest,
                        exit_code=process.returncode,
                        executed_tests=executed,
                        timed_out=timed_out,
                        passed=process.returncode == 0
                        and not timed_out
                        and executed > 0
                        and report.get("passed") is True,
                        stdout=stdout,
                        stderr=stderr,
                    )
                )
            # Verification cannot mutate the candidate or its protected test files.
            observed = await self.workspace.capture(attempt_id, candidate.iteration, spec, candidate, directory)
            if observed.content_digest != candidate.content_digest:
                from langflow.adlc.task_loop_workspace import LiveLoopError

                code = "TASK_LOOP_VERIFIER_MUTATED_CANDIDATE"
                raise LiveLoopError(code)
            return LiveLoopVerification(
                spec_digest=spec.content_digest,
                candidate_id=candidate.candidate_id,
                candidate_digest=candidate.content_digest,
                checks=tuple(checks),
            )
        finally:
            await self.workspace.remove(attempt_id, "verify")
