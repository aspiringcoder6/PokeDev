import hashlib
import json

import pytest

from langflow.adlc.native_source_context import context_parts, pack_sources


def read(result, namespace, path):
    entry = json.loads(result["source-index.json"])["sources"][namespace][path]
    body = result[entry["input"]]
    assert hashlib.sha256(body.encode()).hexdigest() == entry["sha256"]
    return body


def test_approved_unicode_context_is_split_without_losing_a_character():
    text = "Yêu cầu đã duyệt\n" * 18000
    parts = context_parts(text)
    assert "context.md" in parts and "context-extra-01.md" in parts
    assert "".join(parts.values()) == text
    assert all(len(value.encode()) <= 150000 for value in parts.values())


def test_granted_source_and_changed_baseline_survive_budget_with_exact_content():
    original = "old source\n" * 1000
    updated = "new source\n" * 1000
    optional = {f"unused/{n}.java": "optional\n" * 2000 for n in range(80)}
    files = {**optional, "service.java": updated}
    result = pack_sources({"context.md": "Approved task"}, [
        ("source", files), ("baseline-source", {"service.java": original})],
        required_paths=["service.java"], wire_limit=80000)
    assert read(result, "source", "service.java") == updated
    assert read(result, "baseline-source", "service.java") == original
    assert json.loads(result["source-index.json"])["optional_omitted"] > 0
    assert len(json.dumps({"inputs": result}).encode()) <= 80000
    assert files["service.java"] == updated


def test_wire_budget_includes_ascii_escaping_and_each_input_meets_bridge_limit():
    value = '"Dữ liệu\\\n' * 3000
    result = pack_sources({"context.md": "Yêu cầu"}, [("source", {"A.java": value})], required_paths=["A.java"])
    assert read(result, "source", "A.java") == value
    assert all(len(body.encode()) <= 180000 for body in result.values())
    assert len(json.dumps({"inputs": result}).encode()) <= 1450000


def test_an_oversized_mandatory_file_fails_instead_of_becoming_a_partial_baseline():
    with pytest.raises(ValueError, match="LIVE_NATIVE_CONTEXT_LIMIT"):
        pack_sources({"context.md": "Approved"}, [("source", {"A.java": "x" * 180001})], required_paths=["A.java"])


def test_optional_repository_context_is_bounded_separately_from_complete_granted_files():
    files = {"Required.java": "full original source", **{f"Unrelated{n}.java": "x" * 2000 for n in range(80)}}
    result = pack_sources({"context.md": "Approved"}, [("source", files)], required_paths=["Required.java"], optional_budget=10000)
    assert read(result, "source", "Required.java") == files["Required.java"]
    assert json.loads(result["source-index.json"])["optional_omitted"] > 70
    assert len(json.dumps({"inputs": result}).encode()) < 12000
