"""Publish complete JSON snapshots despite short Windows reader/antivirus locks."""

import json
import os
from pathlib import Path
import tempfile
import threading
import time

_writers = threading.RLock()


class SnapshotBusyError(OSError):
    def __init__(self):
        super().__init__("LIVE_SNAPSHOT_STORAGE_BUSY")


def read_json_atomic(path):
    for attempt in range(12):
        try:
            return json.loads(Path(path).read_text(encoding="utf8"))
        except PermissionError:
            if attempt == 11:
                raise SnapshotBusyError() from None
            time.sleep(min(0.02 * (2 ** attempt), 0.2))


def write_json_atomic(path, value):
    path = Path(path)
    temporary = None
    with _writers:
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf8", dir=path.parent,
                    prefix="." + path.name + ".", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(value, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            for attempt in range(12):
                try:
                    temporary.replace(path)
                    return
                except PermissionError:
                    if attempt == 11:
                        raise SnapshotBusyError() from None
                    # Retrying a local rename never repeats an agent or job.
                    time.sleep(min(0.02 * (2 ** attempt), 0.2))
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except PermissionError:
                    pass  # Preserve the original error if a scanner holds the temp file.
