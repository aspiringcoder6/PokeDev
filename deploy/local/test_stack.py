import base64
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("pokedev_local_stack", Path(__file__).with_name("stack.py"))
stack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stack)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(stack, "ROOT", tmp_path)
    monkeypatch.setattr(stack, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(stack, "STATE", tmp_path / "adlc-flow/data/local")
    (tmp_path / ".env.example").write_text("# local settings\nVAI_PLATFORM_TOKEN=\n", encoding="utf-8")
    return tmp_path


def test_init_is_idempotent_and_key_supports_fernet(isolated):
    stack.init()
    first = stack.read_env()
    assert all(first[key] for key in stack.SECRET_KEYS)
    assert len(base64.urlsafe_b64decode(first["LANGFLOW_SECRET_KEY"])) == 32
    stack.init()
    assert stack.read_env() == first


def test_init_preserves_user_credentials_and_comments(isolated):
    stack.ENV_FILE.write_text("# keep this\nVAI_PLATFORM_TOKEN=owned-token\nPOKEDEV_DB_PASSWORD=owned-password\n", encoding="utf-8")
    stack.init()
    assert stack.read_env()["VAI_PLATFORM_TOKEN"] == "owned-token"
    assert stack.read_env()["POKEDEV_DB_PASSWORD"] == "owned-password"
    assert stack.ENV_FILE.read_text().startswith("# keep this\n")


def test_independent_installs_generate_different_credentials(isolated, monkeypatch):
    stack.init()
    first = stack.read_env()
    monkeypatch.setattr(stack, "ENV_FILE", isolated / ".env.second")
    stack.init()
    second = stack.read_env()
    assert all(first[key] != second[key] for key in stack.SECRET_KEYS)


def test_reconnect_handles_missing_launch_token_without_clearing_saved_token(isolated, monkeypatch):
    stack.update_env({"VAI_PLATFORM_TOKEN": "existing"})
    monkeypatch.setattr(stack, "compose", lambda *a, **k: type("Logs", (), {"stdout": "Harness failed to start"})())
    assert stack.sync_harness_token() is False
    assert stack.read_env()["VAI_PLATFORM_TOKEN"] == "existing"


def test_compose_uses_this_projects_credentials_over_inherited_environment(isolated, monkeypatch):
    stack.update_env({"ADLC_HARNESS_API_TOKEN": "this-project-token"})
    monkeypatch.setenv("ADLC_HARNESS_API_TOKEN", "another-project-token")
    captured = {}
    def capture(args, **kwargs):
        captured.update(kwargs)
    monkeypatch.setattr(stack, "execute", capture)
    stack.compose("config", "--quiet")
    assert captured["env"]["ADLC_HARNESS_API_TOKEN"] == "this-project-token"
