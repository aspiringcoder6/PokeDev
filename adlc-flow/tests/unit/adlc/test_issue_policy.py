import asyncio
import copy

import pytest

from langflow.adlc.issue_policy import (
    POLICY_DEFAULTS,
    assess_issue,
    fingerprint,
    normalize_allowed_paths,
    path_allowed,
    risk_assessment,
    triage_issue,
)
from langflow.adlc.human_inputs import ActiveClock, wait_active


def issue(**changes):
    return {
        "title": "Add a click counter",
        "body": "The counter must show the number of clicks and keep the reset action.",
        **changes,
    }


def policy(**changes):
    return {
        **POLICY_DEFAULTS,
        "mode": "risk",
        "watch_issues": True,
        "revision": 1,
        "auto_allowed_paths": ["src/components/**", "tests/**"],
        **changes,
    }


def plan(**changes):
    return {
        "digest": "a" * 64,
        "tasks": [
            {
                "title": "Implement the click counter",
                "write_paths": ["src/components/Counter.tsx"],
                "steps": ["Count user clicks"],
                "acceptance": ["The counter must increment"],
            },
            {
                "title": "Test the click counter",
                "write_paths": ["tests/test_counter.py"],
                "steps": ["Test the count"],
                "acceptance": ["Reset must still work"],
            },
        ],
        "commands": [{"argv": ["python", "-m", "unittest", "discover", "-s", "tests"]}],
        **changes,
    }


def clarification(source, **changes):
    return {
        "source_digest": fingerprint([source["title"], source["body"]]),
        "answers": {
            "goal": "A counter that increments on each click",
            "scope": "Only the counter component and its tests",
            "acceptance": "Three clicks must display three and reset must display zero",
        },
        "approach": "spec_first",
        **changes,
    }


def test_triage_explains_ready_issue_without_calling_an_agent():
    result = triage_issue(issue())
    assert result["action"] == "ready" and result["questions"] == []
    assert result["reasons"] and result["version"] and len(result["input_digest"]) == 64


@pytest.mark.parametrize(
    "source",
    [
        issue(body="Please fix it"),
        issue(body="TBD: discuss the behavior with the team after the meeting."),
        issue(title="Thiết kế lại kiến trúc", body="Tích hợp nhiều phần của ứng dụng thành một sản phẩm mới."),
    ],
)
def test_missing_or_broad_requirements_ask_for_goal_scope_and_acceptance(source):
    result = triage_issue(source)
    assert result["action"] in {"needs_spec", "needs_human"}
    assert {q["id"] for q in result["questions"]} == {"goal", "scope", "acceptance"}


def test_clarifications_are_bound_to_the_current_source_and_preserve_spec_first():
    source = issue(body="TBD")
    answer = clarification(source)
    ready = triage_issue(source, answer)
    assert ready["action"] == "ready" and ready["planning_style"] == "spec_first"
    changed = triage_issue({**source, "body": "Changed unclear request"}, answer)
    assert changed["action"] == "needs_human" and changed["input_digest"] != ready["input_digest"]


def test_risk_uses_the_highest_factor_even_for_an_otherwise_small_change():
    result = risk_assessment(issue(body="The reset must also change payment permissions."), plan=plan())
    assert result["tier"] == "R3" and any(f["factor"] == "sensitivity" for f in result["factors"])


def test_read_only_requests_are_r0_until_the_actual_plan_proposes_writes():
    source = issue(title="Summarize counter behavior")
    assert risk_assessment(source)["tier"] == "R0"
    assert risk_assessment(source, plan=plan())["tier"] == "R1"


@pytest.mark.parametrize(
    "path,expected",
    [
        ("src/auth/roles.py", "R3"),
        ("src/security.py", "R3"),
        ("src/secrets.key", "R3"),
        (".env", "R3"),
        ("migrations/004.sql", "R2"),
        ("package.json", "R2"),
        (".gitea/workflows/release.yml", "R2"),
    ],
)
def test_actual_plan_paths_override_benign_issue_wording(path, expected):
    result = risk_assessment(issue(), plan=plan(tasks=[{"write_paths": [path]}]))
    assert result["tier"] == expected


def test_risk_mode_requires_all_exact_write_paths_to_fit_the_scopes():
    assert assess_issue(issue(), None, policy(), plan())["auto_decision"]["allowed"] is True
    outside = plan(tasks=[{"write_paths": ["src/components-old/Counter.tsx"]}])
    result = assess_issue(issue(), None, policy(), outside)
    assert result["auto_decision"]["code"] == "ISSUE_PATH_REVIEW_REQUIRED"


@pytest.mark.parametrize(
    "paths",
    [
        ["/**"],
        ["**"],
        ["../app.py"],
        ["src/../app.py"],
        ["C:/app.py"],
        ["src\\app.py"],
        ["src/*"],
        [".git/**"],
        [".env"],
    ],
)
def test_scope_settings_reject_escaping_or_unbounded_patterns(paths):
    with pytest.raises(ValueError, match="ISSUE_ALLOWED_PATHS_INVALID"):
        normalize_allowed_paths(paths)


def test_scope_prefixes_have_a_directory_boundary():
    scopes = normalize_allowed_paths(["docs/**", "app.js", "docs/**"])
    assert scopes == ["docs/**", "app.js"]
    assert path_allowed("docs/guide.md", scopes) and path_allowed("app.js", scopes)
    assert not path_allowed("docs-old/guide.md", scopes)
    assert not path_allowed("other/app.js", scopes)


@pytest.mark.parametrize(
    "argv",
    [
        ["sh", "-c", "echo ok && deploy"],
        ["curl", "https://example.com"],
        ["git", "push"],
        ["python", "-c", "print('ok')"],
        ["npm", "run", "release"],
        ["python", "-m", "pytest", "--override-ini=addopts=--doctest-modules"],
    ],
)
def test_arbitrary_commands_require_human_review_in_all_automatic_modes(argv):
    for mode in ("risk", "auto"):
        result = assess_issue(issue(), None, policy(mode=mode), plan(commands=[{"argv": argv}]))
        assert result["risk"]["level"] >= 2
        assert result["auto_decision"]["allowed"] is False


def test_unknown_or_missing_plan_evidence_never_auto_approves():
    assert assess_issue(issue(), None, policy(mode="auto"), {"digest": "x"})["auto_decision"]["allowed"] is False
    service = plan(preview={"argv": ["python", "server.py"]})
    assert assess_issue(issue(), None, policy(), service)["auto_decision"]["allowed"] is False


def test_risk_is_checked_again_after_the_plan_changes():
    safe = plan()
    assert assess_issue(issue(), None, policy(), safe)["auto_decision"]["allowed"]
    revised = copy.deepcopy(safe)
    revised["tasks"][0]["write_paths"] = ["src/auth/permissions.py"]
    assert not assess_issue(issue(), None, policy(), revised)["auto_decision"]["allowed"]


@pytest.mark.asyncio
async def test_active_time_limit_pauses_for_a_person_and_reports_spent_time(monkeypatch):
    from langflow.adlc import human_inputs

    instant, ticks, elapsed = [0.0], [0], []
    monkeypatch.setattr(human_inputs, "ActiveClock", lambda: ActiveClock(lambda: instant[0]))
    done = asyncio.Event()

    async def job():
        await done.wait()
        return "finished"

    def waiting():
        ticks[0] += 1
        paused = ticks[0] <= 5
        instant[0] += 1000 if paused else 1
        if not paused:
            done.set()
        return paused

    assert await wait_active(job(), waiting, 3, poll_s=0, progress=elapsed.append) == "finished"
    assert max(elapsed) < 3 and elapsed[:5] == [0] * 5


@pytest.mark.asyncio
async def test_active_timeout_cancels_the_local_work_instead_of_leaving_it_running(monkeypatch):
    from langflow.adlc import human_inputs

    instant, canceled = [0.0], []
    monkeypatch.setattr(human_inputs, "ActiveClock", lambda: ActiveClock(lambda: instant[0]))

    async def job():
        try:
            await asyncio.Event().wait()
        finally:
            canceled.append(True)

    def waiting():
        instant[0] += 1
        return False

    with pytest.raises(TimeoutError):
        await wait_active(job(), waiting, 2, poll_s=0)
    assert canceled == [True]
