"""Vietnamese display metadata must keep API identifiers and user content intact."""

# ruff: noqa: S101 -- pytest assertions are the checks under test.

import copy
import json
from pathlib import Path

import pytest

from langflow.utils import i18n


@pytest.fixture
def real_catalogs(monkeypatch):
    monkeypatch.setattr(i18n, "_translations", {})
    i18n.get_supported_locales()
    locale_dir = Path(i18n.__file__).resolve().parent.parent / "locales"
    return {code: json.loads((locale_dir / f"{code}.json").read_text(encoding="utf-8")) for code in ("en", "vi")}


def test_vietnamese_covers_all_metadata_keys(real_catalogs):
    assert "vi" in i18n.get_supported_locales()
    assert real_catalogs["vi"].keys() == real_catalogs["en"].keys()
    assert all(isinstance(value, str) and value.strip() for value in real_catalogs["vi"].values())


@pytest.mark.usefixtures("real_catalogs")
def test_translated_component_preserves_identifiers_schema_and_input_values():
    node = {
        "display_name": "Chat Input",
        "description": "Get chat inputs from the Playground.",
        "template": {
            "api_key": {
                "display_name": "API Key",
                "value": "user-provided-value",
                "type": "str",
                "required": True,
            },
        },
        "outputs": [{"name": "message", "display_name": "Message", "types": ["Message"]}],
    }
    before = copy.deepcopy(node)
    # Use a component present in the real catalog for the display-name assertion.
    translated = i18n.translate_component_node("ChatInput", node, "vi")
    assert translated["display_name"] == "Đầu vào trò chuyện"
    assert translated["template"]["api_key"]["value"] == "user-provided-value"
    assert translated["template"]["api_key"]["type"] == "str"
    assert translated["template"]["api_key"]["required"] is True
    assert translated["outputs"][0]["name"] == "message"
    assert translated["outputs"][0]["types"] == ["Message"]
    assert node == before


@pytest.mark.usefixtures("real_catalogs")
def test_user_authored_notes_are_never_translated():
    user_note = {"type": "noteNode", "data": {"node": {"description": "My API workflow <test>"}}}
    assert i18n.translate_flow_notes([user_note], "vi")[0] is user_note
    assert json.dumps(user_note) == json.dumps(i18n.translate_flow_notes([user_note], "vi")[0])
