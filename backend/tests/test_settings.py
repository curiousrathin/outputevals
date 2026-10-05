import os
import stat

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core import llm
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr("app.core.secrets.ROOT", tmp_path)  # ignore the real .env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return TestClient(app)


def test_status_when_unconfigured(client):
    body = client.get("/api/settings/anthropic").json()
    assert body == {
        "configured": False,
        "source": "none",
        "masked_key": None,
        "model": settings.llm_model,
    }


def test_reads_dotenv_and_ignores_placeholder(client, tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-your-key-here\n")
    assert client.get("/api/settings/anthropic").json()["configured"] is False

    env.write_text("ANTHROPIC_API_KEY=sk-ant-api03-from-dotenv-file-1234\n")
    status = client.get("/api/settings/anthropic").json()
    assert status["source"] == "dotenv" and status["masked_key"].endswith("1234")


def test_rejects_malformed_key(client):
    assert client.put("/api/settings/anthropic", json={"api_key": "not-a-key"}).status_code == 422


def test_invalid_key_is_not_saved(client, monkeypatch):
    bad = llm.KeyCheck(False, "Invalid API key.")
    monkeypatch.setattr("app.api.settings.check_key", lambda key=None, model=None: bad)
    body = client.put("/api/settings/anthropic", json={"api_key": "sk-ant-bad"}).json()
    assert body["ok"] is False
    assert client.get("/api/settings/anthropic").json()["configured"] is False


def test_valid_key_is_saved_masked_and_private(client, monkeypatch, tmp_path):
    ok = llm.KeyCheck(True, "Connected.", model="claude-opus-5-5")
    monkeypatch.setattr("app.api.settings.check_key", lambda key=None, model=None: ok)
    key = "sk-ant-api03-abcdefghijklmnop-WXYZ"
    assert client.put("/api/settings/anthropic", json={"api_key": key}).json()["ok"] is True

    status = client.get("/api/settings/anthropic").json()
    assert status["configured"] and status["source"] == "saved"
    assert key not in status["masked_key"] and status["masked_key"].endswith("WXYZ")
    assert stat.S_IMODE(os.stat(tmp_path / "secrets.json").st_mode) == 0o600

    assert client.delete("/api/settings/anthropic").json()["configured"] is False
