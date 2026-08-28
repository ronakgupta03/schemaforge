"""Tests for the lazy-config behavior (no real DB needed)."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import pytest

# The server module must be importable without DATABASE_URL set.
_temp_state = tempfile.TemporaryDirectory()
os.environ.pop("DATABASE_URL", None)
os.environ["SF_MCP_CONFIG_TOKEN"] = "test-token"
os.environ["SF_CONFIG_PORT"] = "19001"
os.environ["SF_STATE_DIR"] = _temp_state.name

_spec = importlib.util.spec_from_file_location(
    "postgres_server", str(Path(__file__).parent / "server.py")
)
mcp_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mcp_server)
def __dir__():
    sys.modules.pop("test_config", None)
    return list(globals().keys())

@pytest.fixture(scope="module")
def config_server():
    port = mcp_server.CONFIG_PORT
    t = threading.Thread(target=mcp_server.run_config_server, daemon=True)
    t.start()
    for _ in range(50):
        try:
            httpx.get(f"http://127.0.0.1:{port}/config", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    mcp_server._config_httpd.shutdown()


def test_tools_raise_when_unconfigured():
    with pytest.raises(RuntimeError, match="not configured"):
        mcp_server._conn()


def test_config_rejects_bad_token(config_server):
    r = httpx.post(f"{config_server}/config", json={"database_url": "postgresql://x/y"},
                   headers={"Authorization": "Bearer wrong"}, timeout=5)
    assert r.status_code == 401


def test_config_sets_dsn(config_server):
    r = httpx.post(f"{config_server}/config", json={"database_url": "postgresql://u:p@h:5432/db"},
                   headers={"Authorization": "Bearer test-token"}, timeout=5)
    assert r.status_code == 202
    assert mcp_server._config["database_url"] == "postgresql://u:p@h:5432/db"


def test_config_persists_and_reloads(config_server, tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "STATE_DIR", str(tmp_path))
    mcp_server._save_config()
    os.environ.pop("DATABASE_URL", None)
    fresh = mcp_server._load_config()
    assert fresh["database_url"] == "postgresql://u:p@h:5432/db"
