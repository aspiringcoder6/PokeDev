"""Publish reviewed bridge source to its existing Gitea repo; credentials stay in process env."""
from pathlib import Path
import base64
import hashlib
import json
import os
import shutil
import subprocess
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "integration-sources/pokedev-services-plugin"

def publish():
    config = {**dotenv_values(ROOT / ".env.vai-platform.local"), **os.environ}
    version = json.loads((SOURCE / "package.json").read_text())["version"]
    checkout = ROOT / "adlc-flow/data/plugin-publish" / ("services-" + version)
    base = config.get("VAI_GITEA_URL", "http://10.0.10.195:3000").rstrip("/")
    url = base + "/admin/vai-pokedev-services.git"
    auth = base64.b64encode((config.get("VAI_GITEA_USER", "admin") + ":" + config["VAI_GITEA_TOKEN"]).encode()).decode()
    env = {k: v for k, v in os.environ.items() if k.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="http.extraHeader", GIT_CONFIG_VALUE_0="Authorization: Basic " + auth,
        GIT_CONFIG_KEY_1="http.proxy", GIT_CONFIG_VALUE_1="", GIT_HTTP_LOW_SPEED_LIMIT="1", GIT_HTTP_LOW_SPEED_TIME="30")
    def git(*args):
        process = subprocess.run(["git", *args], env=env, cwd=ROOT, capture_output=True, text=True, timeout=120)
        if process.returncode:
            safe = process.stderr.replace(config["VAI_GITEA_TOKEN"], "[redacted]").replace(auth, "[redacted]")
            raise RuntimeError("Gitea publication step failed: " + args[0] + " " + safe[:1000])
        return process.stdout.strip()
    if not checkout.exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "--depth", "1", url, str(checkout))
    paths = [SOURCE / "package.json", SOURCE / "cordis.patch.yml", SOURCE / "README.md", *sorted((SOURCE / "lib").rglob("*")), *sorted((SOURCE / "test").rglob("*"))]
    hashes = {}
    for file in paths:
        if not file.is_file():
            continue
        relative = file.relative_to(SOURCE)
        target = checkout / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)
        hashes[relative.as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    git("-C", str(checkout), "add", "package.json", "cordis.patch.yml", "README.md", "lib", "test")
    if git("-C", str(checkout), "status", "--porcelain"):
        git("-C", str(checkout), "-c", "user.name=PokeDev", "-c", "user.email=pokedev@localhost", "commit", "-m", "Add project Workloop Sandbox verification bridge " + version)
        git("-C", str(checkout), "push", "origin", "HEAD:main")
    revision = git("-C", str(checkout), "rev-parse", "HEAD")
    receipt = {"plugin": "vai-pokedev-services", "version": version, "revision": revision,
               "repository": url.removesuffix(".git"), "install_source": "git+" + url + "#" + revision, "files": hashes}
    output = ROOT / "integration-sources/plugin-releases/vai-pokedev-services" / version
    output.mkdir(parents=True, exist_ok=True)
    (output / "release.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({k: v for k, v in receipt.items() if k != "files"}, ensure_ascii=False))

if __name__ == "__main__":
    publish()
