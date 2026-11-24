from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading

import pytest

from langflow.adlc.atomic_data import SnapshotBusyError, read_json_atomic, write_json_atomic


def test_short_windows_reader_lock_retries_only_rename_and_keeps_complete_old_value(tmp_path, monkeypatch):
    target = tmp_path / "result.json"
    target.write_text('{"old":true}')
    replace = Path.replace
    attempts = []

    def locked(path, destination):
        attempts.append(path)
        assert json.loads(target.read_text()) == {"old": True}
        if len(attempts) < 4:
            raise PermissionError(5, "Access is denied")
        return replace(path, destination)

    monkeypatch.setattr(Path, "replace", locked)
    write_json_atomic(target, {"new": "Dữ liệu nguyên vẹn"})
    assert json.loads(target.read_text()) == {"new": "Dữ liệu nguyên vẹn"}
    assert len(attempts) == 4 and len(set(attempts)) == 1
    assert list(tmp_path.glob("*.tmp")) == []


def test_parallel_writers_publish_valid_snapshots_while_a_reader_polls(tmp_path):
    target = tmp_path / "result.json"
    write_json_atomic(target, {"writer": -1, "body": "initial"})
    stopping = threading.Event()
    failures = []

    def reader():
        while not stopping.is_set():
            try:
                assert isinstance(read_json_atomic(target)["writer"], int)
            except Exception as error:
                failures.append(type(error).__name__)

    observer = threading.Thread(target=reader)
    observer.start()
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda n: write_json_atomic(target, {"writer": n, "body": str(n) * 10000}), range(16)))
    finally:
        stopping.set()
        observer.join(timeout=3)
    assert not failures
    assert json.loads(target.read_text())["writer"] in range(16)
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_real_write_failure_is_not_hidden_or_retried_as_an_agent_action(tmp_path, monkeypatch):
    target = tmp_path / "result.json"
    def broken(*_args):
        raise OSError("storage failure")
    monkeypatch.setattr(Path, "replace", broken)
    with pytest.raises(OSError, match="storage failure"):
        write_json_atomic(target, {"state": "RUNNING"})
    assert not target.exists() and list(tmp_path.glob("*.tmp")) == []


def test_readers_retry_a_short_replace_lock_and_exhaustion_is_recoverable(tmp_path, monkeypatch):
    target = tmp_path / "result.json"
    target.write_text('{"state":"RUNNING"}')
    original = Path.read_text
    attempts = []
    def locked(path, *args, **kwargs):
        attempts.append(path)
        if len(attempts) <= 2:
            raise PermissionError(5, "Access is denied")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", locked)
    assert read_json_atomic(target) == {"state": "RUNNING"}
    assert len(attempts) == 3
    monkeypatch.setattr("langflow.adlc.atomic_data.time.sleep", lambda _delay: None)
    def always_locked(*_args, **_kwargs):
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(Path, "read_text", always_locked)
    from langflow.adlc.project_recovery import recoverable_error
    with pytest.raises(SnapshotBusyError) as error:
        read_json_atomic(target)
    assert recoverable_error(error.value)
