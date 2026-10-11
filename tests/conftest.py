"""Shared fixtures: offline API-only test app (no audio hardware, no network)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("VOICE_AGENT_DISABLE_ENGINE", "1")

import app as app_module  # noqa: E402


class FakeMonitor:
    def check_adb_connection(self):
        return False


class FakeGemini:
    mode = "sales"


class FakeCallLogger:
    def __init__(self):
        self.saved = []

    def get_leads(self, status="new"):
        return list(self.saved)

    def save_lead(self, name, phone, company="", interest="", notes="", call_id=None):
        self.saved.append({"name": name, "phone": phone})
        return len(self.saved)


class FakeEngine:
    def __init__(self):
        self.call_logger = FakeCallLogger()
        self.gemini = FakeGemini()
        self.monitor = FakeMonitor()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    app_module._engine = FakeEngine()
    app_module._admin_buckets.clear()
    with TestClient(app_module.fastapi_app, raise_server_exceptions=False) as c:
        yield c
    app_module._engine = None


@pytest.fixture()
def key():
    return "test-admin-key"


@pytest.fixture(autouse=True)
def admin_key_env(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")


@pytest.fixture()
def no_admin_key(monkeypatch):
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
