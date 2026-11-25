"""TraceRecorder: each step runs via high-level browser actions, then ground truth is captured read-only.

Driver protocol (duck-typed, implemented by playwright_driver.PlaywrightDriver):
    url() -> str
    aria_snapshot() -> str
    network_events() -> list[{"method", "path", "status"}]
    storage_entries() -> list[{"origin", "key", "value"}]
    actor -> str

Actions MUST use Playwright high-level APIs so the synthesized script can replay
exactly the behavior that was grounded. Read-only CDP/evaluate probing belongs to
the driver, never to action implementation.
"""
import time

from .session import DeviationError, ExplorerError


class TraceRecorder:
    def __init__(self, session, driver, step_deadline_ms=30000):
        self.session = session
        self.driver = driver
        self.step_deadline_ms = int(step_deadline_ms)
        self._seen_storage = {e["key"]: e["value"] for e in driver.storage_entries()}

    def record(self, step_id, intent, selected_action, action, chosen_locator="", target="",
               candidates=None, status_if_ok="GROUNDED", observed_extra=None):
        """Execute one bounded step, then capture URL/ARIA/network/storage evidence."""
        self.session.check_total_deadline()
        step_dir = self.session.root / step_id
        step_dir.mkdir(parents=True, exist_ok=True)
        started = time.time()
        status, error = status_if_ok, None
        try:
            action(self.driver)
        except DeviationError as exc:
            status, error = "DEVIATED", str(exc)
        except Exception as exc:
            status, error = "FAILED", f"{type(exc).__name__}: {exc}"
        if (time.time() - started) * 1000 > self.step_deadline_ms:
            status, error = "FAILED", f"Step deadline exceeded: {self.step_deadline_ms}ms"
        try:
            self.session.check_total_deadline()
        except ExplorerError as exc:
            status, error = "FAILED", str(exc)

        current_storage = self.driver.storage_entries()
        changes = [e for e in current_storage if self._seen_storage.get(e["key"]) != e["value"]]
        self._seen_storage = {e["key"]: e["value"] for e in current_storage}

        snapshot = self.driver.aria_snapshot()
        (step_dir / "aria.yml").write_text(snapshot, encoding="utf-8")
        network_events = self.driver.network_events()

        observed = {"aria_snapshot_chars": len(snapshot)}
        if error:
            observed["error"] = error
        if observed_extra:
            observed.update(observed_extra)
        record = {
            "step_id": step_id,
            "user_intent": intent,
            "status": status,
            "selected_action": selected_action,
            "target": target,
            "locator_candidates": candidates or [],
            "chosen_locator": chosen_locator,
            "aria_snapshot_ref": f"trace://{self.session.run_id}/{step_id}/aria.yml",
            "network_events": network_events,
            "url": self.driver.url(),
            "storage_changes": changes,
            "observed_ui": observed,
            "actor": self.driver.actor,
            "started_at": _ts(started),
            "ended_at": _ts(time.time()),
        }
        self.session.append_record(record)
        return record

    def coverage_gate(self, required_steps):
        from .trace import build_coverage
        return build_coverage(required_steps, self.session.records)


def _ts(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))
