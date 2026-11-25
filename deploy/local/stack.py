"""Independent local PokeDev stack. Uses only the Python standard library."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"
STATE = ROOT / "adlc-flow/data/local"
VENV = ROOT / "adlc-flow/.venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
CORE = ["postgres", "redis", "app"]
SERVICES = {*CORE, "harness", "opensandbox", "vfs", "sandbox", "memory", "memory-mcp", "testforge"}
SECRET_KEYS = ["POKEDEV_DB_PASSWORD", "POKEDEV_MEMORY_PASSWORD", "LANGFLOW_SECRET_KEY",
               "LANGFLOW_SUPERUSER_PASSWORD", "ADLC_HARNESS_API_TOKEN", "ADLC_HARNESS_CALLBACK_SECRET",
               "ADLC_SANDBOX_BROKER_TOKEN", "OPENSANDBOX_API_KEY", "TESTFORGE_BROKER_TOKEN"]


def read_env(path: Path | None = None) -> dict[str, str]:
    path = path or ENV_FILE
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() and not key.lstrip().startswith("#"):
                values[key.strip()] = value.strip().strip("\"'")
    return values


def update_env(changes: dict[str, str], path: Path | None = None) -> None:
    path = path or ENV_FILE
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    remaining = dict(changes)
    for index, line in enumerate(lines):
        key = line.partition("=")[0].strip()
        if key in remaining and not line.lstrip().startswith("#"):
            lines[index] = f"{key}={remaining.pop(key)}"
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def init() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "project-source").mkdir(exist_ok=True)
    (ROOT / "data").mkdir(exist_ok=True)
    if not ENV_FILE.exists():
        shutil.copyfile(ROOT / ".env.example", ENV_FILE)
    current = read_env()
    update_env({key: (base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
                      if key == "LANGFLOW_SECRET_KEY" else secrets.token_urlsafe(36))
                for key in SECRET_KEYS if not current.get(key)})
    print("Local configuration ready (.env); existing settings preserved.")


def execute(args: list[str], *, cwd: Path = ROOT, env: dict | None = None, capture=False):
    # Windows .cmd executables need their resolved path; arguments stay separate.
    executable = shutil.which(args[0]) or args[0]
    return subprocess.run([executable, *args[1:]], cwd=cwd, env=env, check=True,
                          text=True, encoding="utf-8", errors="replace",
                          capture_output=capture)


def compose(*args: str, capture=False):
    return execute(["docker", "compose", "--project-name", "pokedev-local", "--env-file", str(ENV_FILE),
                    "-f", str(ROOT / "compose.yml"), *args],
                   env={**os.environ, **read_env(), "COMPOSE_PARALLEL_LIMIT": "1"}, capture=capture)


def build(services: list[str]) -> None:
    buildable = ["app", "harness", "sandbox", "vfs", "memory", "testforge"]
    for service in services or buildable:
        if service == "memory-mcp":
            service = "memory"
        if service in buildable:
            compose("build", service)


def prepare_sandbox_images() -> None:
    for image in ("opensandbox/execd:v1.0.22", "python:3.12-alpine"):
        try:
            execute(["docker", "image", "inspect", "--format", "{{.Id}}", image], capture=True)
        except subprocess.CalledProcessError:
            execute(["docker", "pull", image])


def sync_harness_token() -> bool:
    logs = compose("logs", "--no-color", "--tail", "250", "harness", capture=True).stdout
    matches = re.findall(r"https?://[^\s]*[?&]token=([^&\s\x1b]+)", logs)
    if not matches:
        print("Harness launch token not found. Check 'logs harness' and rerun 'connect-harness'.")
        return False
    token = urllib.parse.unquote(matches[-1])
    update_env({"VAI_PLATFORM_TOKEN": token, "ADLC_BLUEPRINT_DSH_TOKEN": token})
    print("Fresh Harness sign-in configured for this PokeDev instance.")
    return True


def setup() -> None:
    init()
    env = {**os.environ, "UV_CACHE_DIR": str(STATE / "cache/uv"),
           "PIP_CACHE_DIR": str(STATE / "cache/pip"), "npm_config_cache": str(STATE / "cache/npm"),
           "PUPPETEER_SKIP_DOWNLOAD": "true", "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1"}
    if not PYTHON.exists():
        if shutil.which("uv"):
            execute(["uv", "venv", str(VENV), "--python", "3.14"], env=env)
        else:
            if sys.version_info[:2] != (3, 14):
                raise RuntimeError("Install Python 3.14 or uv, then rerun setup.")
            execute([sys.executable, "-m", "venv", str(VENV)], env=env)
    pip = ["uv", "pip", "install", "--python", str(PYTHON)] if shutil.which("uv") else [str(PYTHON), "-m", "pip", "install"]
    execute([*pip, "-r", "deploy/local/requirements.lock.txt"], env=env)
    execute([*pip, "--no-deps", "-e", ".", "-e", "sdk"], env=env)
    frontend = ROOT / "adlc-flow/frontend"
    execute(["npm", "ci", "--no-audit", "--no-fund"], cwd=frontend, env=env)
    build_frontend(env)


def build_frontend(env=None) -> None:
    env = {**(env or os.environ), "GOMAXPROCS": "2", "GOMEMLIMIT": "768MiB",
           "NODE_OPTIONS": "--max-old-space-size=3072"}
    if os.name == "nt":
        execute(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "deploy/build_frontend.ps1"], env=env)
    else:
        execute(["npx", "vite", "build"], cwd=ROOT / "adlc-flow/frontend", env=env)


def run_native() -> None:
    init()
    if not PYTHON.exists() or not (ROOT / "adlc-flow/frontend/build/index.html").exists():
        raise RuntimeError("Run 'python deploy/local/stack.py setup' first.")
    env = {**os.environ, **read_env(), "LANGFLOW_CONFIG_DIR": str(STATE / "config"),
           "DO_NOT_TRACK": "true", "LANGFLOW_DO_NOT_TRACK": "true"}
    execute([str(PYTHON), "-m", "langflow", "run", "--host", "127.0.0.1", "--port", "7862",
             "--workers", "1", "--frontend-path", str(ROOT / "adlc-flow/frontend/build"),
             "--no-open-browser"], env=env)


def status(core_only: bool = False) -> None:
    compose("ps")
    endpoints = {"PokeDev": "http://127.0.0.1:7862/health_check",
                 "Harness": "http://127.0.0.1:3082/api/v1/adlc-harness/health",
                 "Sandbox": "http://127.0.0.1:8002/health",
                 "OpenSandbox": "http://127.0.0.1:8082/health",
                 "Memory": "http://127.0.0.1:8012/health",
                 "TestForge": "http://127.0.0.1:9092/api/v1/health"}
    if core_only:
        endpoints = {"PokeDev": endpoints["PokeDev"]}
    failed = []
    for name, url in endpoints.items():
        headers = {"Authorization": "Bearer " + read_env().get("ADLC_HARNESS_API_TOKEN", "")} if name == "Harness" else {}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as response:
                payload = response.read().decode("utf-8")
                print(f"{name}: HTTP {response.status}")
                if name == "Harness":
                    health = json.loads(payload)
                    print("  execution_ready=" + str(health.get("ready", False)).lower()
                          + "; driver_ready=" + str(health.get("execution_driver_ready", False)).lower()
                          + "; artifacts_ready=" + str(health.get("artifact_capture_ready", False)).lower())
        except (OSError, urllib.error.HTTPError) as error:
            code = getattr(error, "code", "unreachable")
            print(f"{name}: {code}")
            failed.append(name)
    if failed:
        raise RuntimeError("Services not ready: " + ", ".join(failed))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "build", "up", "down", "status", "logs", "setup", "run",
                                            "frontend", "connect-harness", "open-harness"])
    parser.add_argument("services", nargs="*")
    parser.add_argument("--core-only", action="store_true", help="Only app/PostgreSQL/Redis")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    unknown = set(args.services) - SERVICES
    if unknown:
        raise RuntimeError("Unknown service: " + ", ".join(sorted(unknown)))
    if args.command == "init":
        init()
    elif args.command == "setup":
        setup()
    elif args.command == "run":
        run_native()
    elif args.command == "frontend":
        build_frontend()
    else:
        init()
        selected = args.services or (CORE if args.core_only else [])
        if args.command == "build":
            build(selected)
        elif args.command == "up":
            if not args.no_build:
                build(selected)
            if not selected or {"sandbox", "opensandbox"}.intersection(selected):
                prepare_sandbox_images()
            compose("up", "-d", "--wait", "--wait-timeout", "900", *selected)
            if not args.core_only and (not selected or "harness" in selected) and sync_harness_token():
                if not selected or "app" in selected or compose("ps", "-q", "app", capture=True).stdout.strip():
                    compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "300", "app")
        elif args.command == "connect-harness":
            if not sync_harness_token():
                raise RuntimeError("Harness sign-in is unavailable.")
            if compose("ps", "-q", "app", capture=True).stdout.strip():
                compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "300", "app")
            else:
                print("Restart the native PokeDev process to load the updated sign-in.")
        elif args.command == "open-harness":
            if sync_harness_token():
                token = read_env()["VAI_PLATFORM_TOKEN"]
                webbrowser.open("http://127.0.0.1:3082/?" + urllib.parse.urlencode({"token": token}))
        elif args.command == "down":
            compose("down", "--remove-orphans")
        elif args.command == "status":
            status(args.core_only)
        elif args.command == "logs":
            logs = compose("logs", "--no-color", "--tail", "100", *selected, capture=True)
            # A Harness startup URL grants sign-in. Keep it out of shared logs.
            print(re.sub(r"([?&]token=)[^&\s\x1b]+", r"\1[redacted]", logs.stdout + logs.stderr))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.")
    except (RuntimeError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"PokeDev: {exc}", file=sys.stderr)
        sys.exit(1)
