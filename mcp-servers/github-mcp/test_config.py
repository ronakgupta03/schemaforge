"""Tests for the lazy-config behavior (no network calls)."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import pytest

_temp_state = tempfile.TemporaryDirectory()
os.environ.pop("GITHUB_PERSONAL_ACCESS_TOKEN", None)
os.environ["SF_MCP_CONFIG_TOKEN"] = "test-token"
os.environ["SF_CONFIG_PORT"] = "19002"
os.environ["SF_STATE_DIR"] = _temp_state.name
sys.path.insert(0, str(Path(__file__).parent))

import server as mcp_server  # noqa: E402


@pytest.fixture(scope="module")
def config_server():
    port = int(os.environ["SF_CONFIG_PORT"])
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


def test_client_raises_when_unconfigured():
    with pytest.raises(RuntimeError, match="not configured"):
        mcp_server._client()


def test_config_sets_token_and_repo(config_server):
    r = httpx.post(f"{config_server}/config",
                   json={"token": "ghp_test", "default_repo": "owner/repo"},
                   headers={"Authorization": "Bearer test-token"}, timeout=5)
    assert r.status_code == 202
    assert mcp_server._config["token"] == "ghp_test"
    assert mcp_server._config["default_repo"] == "owner/repo"


def test_repo_defaults_to_default_repo():
    assert mcp_server._resolve_repo("") == "owner/repo"
    assert mcp_server._resolve_repo("other/name") == "other/name"
