"""Download pinned TNQD build inputs. Never executes repository hooks or deployment scripts."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "adlc-flow/data/tnqd-live"
PINS = {
    "tcct-fe-base": "ded8387e93cf3f93e61f677789014e9aa29717ed",
    "tcct-fe-military-youth": "3142ce4557ee2696baece4703883c053da29f59f",
    "tnqd-sut": "791910a9d11c5884e057cf09cc07bd62c2175558",
}

def prepare():
    DEST.mkdir(parents=True, exist_ok=True)
    config = {**dotenv_values(ROOT / ".env.vai-platform.local"), **os.environ}
    base = config.get("VAI_GITEA_URL", "http://10.0.10.195:3000").rstrip("/")
    receipts = []
    with httpx.Client(base_url=base, headers={"Authorization": "token " + config["VAI_GITEA_TOKEN"]},
                      timeout=60, trust_env=False, follow_redirects=False) as client:
        for name, revision in PINS.items():
            archive = DEST / (name + ".zip")
            marker = DEST / (name + ".prepared.json")
            if marker.exists():
                receipts.append(json.loads(marker.read_text(encoding="utf8")))
                continue
            if not archive.exists():
                with client.stream("GET", f"/api/v1/repos/admin/{name}/archive/{revision}.zip") as response:
                    response.raise_for_status()
                    temporary = archive.with_suffix(".part")
                    size = 0
                    with temporary.open("wb") as handle:
                        for chunk in response.iter_bytes(1024 * 1024):
                            size += len(chunk)
                            if size > 512 * 1024 * 1024:
                                raise ValueError("Archive exceeds limit")
                            handle.write(chunk)
                    temporary.replace(archive)
            target = DEST / name
            target.mkdir(exist_ok=True)
            count = 0
            with zipfile.ZipFile(archive) as source:
                for item in source.infolist():
                    parts = Path(item.filename).parts[1:]
                    if not parts or item.is_dir():
                        continue
                    relative = Path(*parts)
                    if name == "tnqd-sut":
                        prefix = Path("FE/military-youth-develop")
                        if not relative.is_relative_to(prefix):
                            continue
                        relative = relative.relative_to(prefix)
                    path = (target / relative).resolve()
                    if not path.is_relative_to(target.resolve()) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError("Unsafe archive path")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(item) as src, path.open("wb") as out:
                        shutil.copyfileobj(src, out)
                    count += 1
            receipt = {"repository": name, "revision": revision, "files": count,
                       "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
            marker.write_text(json.dumps(receipt, indent=2), encoding="utf8")
            receipts.append(receipt)
            print(json.dumps(receipt), flush=True)
    # Build the exact military-youth module from tnqd-sut against the pinned full shell.
    shell = DEST / "tcct-fe-base"
    module = shell / "src/app/modules/military-youth"
    shutil.copytree(DEST / "tnqd-sut", module, dirs_exist_ok=True)
    result = {"inputs": receipts, "shell": str(shell), "module": str(module)}
    (DEST / "sources.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    print("TNQD_SOURCES_READY", flush=True)

if __name__ == "__main__":
    prepare()
