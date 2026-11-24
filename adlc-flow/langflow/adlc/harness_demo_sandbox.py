"""Disposable local Docker sandbox. Never mount the daemon socket, .git or secrets.

This is a bounded demo runner, not a certification of hostile-code isolation.
"""

# ruff: noqa: EM101, PLR2004 - stable public error codes and fixed demo resource/test limits.

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from langflow.adlc.harness_demo_models import DemoError
from langflow.adlc.task_loop_live_models import LiveLoopEvidence, LiveLoopVerification

LIMIT = 8192
READ = "import json,pathlib;print(json.dumps({'content':pathlib.Path('/work/app.py').read_text()}))"
WRITE = "import sys,pathlib;pathlib.Path('/work/app.py').write_bytes(sys.stdin.buffer.read())"


async def process(argv, *, data=None, timeout=45, cwd=None, credential_context=False):
    env = os.environ
    environment = {
        k: env[k] for k in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "DOCKER_HOST", "DOCKER_CONTEXT") if k in env
    }
    if credential_context:
        # Host-side Git/GitHub publisher only. Never forward these to agent containers or prompts.
        for key in (
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "HOMEDRIVE",
            "HOMEPATH",
            "HOME",
            "GH_TOKEN",
            "GITHUB_TOKEN",
        ):
            if key in env:
                environment[key] = env[key]
    child = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=environment,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def drain(stream):
        retained = bytearray()
        while chunk := await stream.read(4096):
            retained.extend(chunk)
            del retained[:-LIMIT]
        return retained.decode("utf-8", errors="replace")

    out, err = asyncio.create_task(drain(child.stdout)), asyncio.create_task(drain(child.stderr))
    try:
        if data:
            child.stdin.write(data)
            await child.stdin.drain()
        child.stdin.close()
        await asyncio.wait_for(child.wait(), timeout)
        return child.returncode, await out, await err
    except BaseException:
        if child.returncode is None:
            child.kill()
        await child.wait()
        await asyncio.gather(out, err)
        raise


class DockerDemoSandbox:
    def __init__(self, image="python:3.12-alpine", *, docker="docker"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./:_@-]{1,250}", image):
            raise DemoError("DEMO_IMAGE_INVALID")
        self.requested_image, self.docker, self.image = image, docker, None
        self.receipts = []

    async def health(self):
        code, out, _ = await process(
            [self.docker, "image", "inspect", "--format", "{{.Id}}", self.requested_image], timeout=10
        )
        if code or not re.fullmatch(r"sha256:[0-9a-f]{64}", out.strip()):
            raise DemoError("DEMO_DOCKER_IMAGE_UNAVAILABLE", 503)
        self.image = out.strip()  # Every execution pins the resolved immutable local image ID.
        return {"backend": "LOCAL_DOCKER", "image_id": self.image, "network": "none"}

    async def run(self, directory: Path, operation: str, *, content=None):
        if operation not in {"read", "write", "checks"}:
            raise DemoError("DEMO_SANDBOX_OPERATION_DENIED", 403)
        if self.image is None:
            await self.health()
        for relative in ("app.py", "test_acceptance.py"):
            path = directory / relative
            if path.is_symlink() or not path.is_file():
                raise DemoError("DEMO_SANDBOX_PATH_DENIED", 403)
        name = "adlc-demo-" + uuid4().hex
        argv = [
            self.docker,
            "run",
            "--rm",
            "--name",
            name,
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            "--memory=128m",
            "--cpus=0.5",
            "--pids-limit=32",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
            "--workdir=/work",
        ]
        # Only one tracked source file and one protected test file; never the Git worktree directory.
        for relative in ("app.py", "test_acceptance.py"):
            path = (directory / relative).resolve()
            if "," in str(path):
                raise DemoError("DEMO_SANDBOX_PATH_DENIED", 403)
            mount = f"type=bind,source={path},target=/work/{relative}"
            if operation != "write" or relative != "app.py":
                mount += ",readonly"
            else:
                path.chmod(0o666)  # Owned disposable worktree only; Git mode stays regular/non-executable.
            argv += ["--mount", mount]
        if operation == "write":
            if not isinstance(content, str) or len(content.encode()) > 65536 or "\0" in content:
                raise DemoError("DEMO_FILE_INVALID", 422)
            argv += ["-i"]
        argv += [self.image, "python", "-B"]
        argv += ["-c", READ if operation == "read" else WRITE] if operation != "checks" else ["test_acceptance.py"]
        timed_out = False
        try:
            code, out, err = await process(argv, data=content.encode() if operation == "write" else None, timeout=30)
        except TimeoutError:
            timed_out, code, out, err = True, -1, "", "Sandbox deadline exceeded."
        finally:
            # Fixed owned container name, not a caller-supplied target. Also runs on cancellation.
            await process([self.docker, "rm", "-f", name], timeout=10)
        receipt = {
            "operation": operation,
            "container_name": name,
            "image_id": self.image,
            "network": "none",
            "non_root": True,
            "read_only_rootfs": True,
            "source_digest": "sha256:" + hashlib.sha256((directory / "app.py").read_bytes()).hexdigest(),
            "test_digest": "sha256:" + hashlib.sha256((directory / "test_acceptance.py").read_bytes()).hexdigest(),
            "exit_code": code,
            "timed_out": timed_out,
            "stdout": out,
            "stderr": err,
        }
        self.receipts.append(receipt)
        if operation == "read" and code == 0:
            receipt["content"] = json.loads(out)["content"]
        if operation != "checks" and (code != 0 or timed_out):
            raise DemoError("DEMO_SANDBOX_OPERATION_FAILED", 502)
        return receipt


class DockerDemoVerifier:
    def __init__(self, workspace, sandbox, record):
        self.workspace, self.sandbox, self.record = workspace, sandbox, record

    async def verify(self, attempt_id, spec, candidate):
        directory = await self.workspace.create(attempt_id, "verify", candidate)
        try:
            receipt = await self.sandbox.run(directory, "checks")
            found = re.search(r"Ran (\d+) tests?", receipt["stderr"])
            count = int(found[1]) if found else 0
            check = LiveLoopEvidence(
                check_id="acceptance",
                argv=("docker", "python", "test_acceptance.py"),
                test_digest=receipt["test_digest"],
                exit_code=receipt["exit_code"],
                executed_tests=count,
                timed_out=receipt["timed_out"],
                passed=receipt["exit_code"] == 0 and count == 4 and not receipt["timed_out"],
                stdout=receipt["stdout"],
                stderr=receipt["stderr"],
            )
            observed = await self.workspace.capture(attempt_id, candidate.iteration, spec, candidate, directory)
            if observed.content_digest != candidate.content_digest:
                raise DemoError("DEMO_VERIFY_MUTATED_CANDIDATE")
            verification = LiveLoopVerification(
                spec_digest=spec.content_digest,
                candidate_id=candidate.candidate_id,
                candidate_digest=candidate.content_digest,
                checks=(check,),
            )
            await self.record("verify", {"verification": verification.model_dump(mode="json"), "reproduction": receipt})
            return verification
        finally:
            await self.workspace.remove(attempt_id, "verify")
