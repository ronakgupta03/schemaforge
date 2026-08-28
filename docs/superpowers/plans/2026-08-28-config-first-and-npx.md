# SchemaForge Config-First + npx Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every SchemaForge integration (MCP servers, model provider/model, sandbox) configurable via the UI — nothing hardcoded, graceful degradation when unconfigured — and ship the whole project as one `npx @schemaforge/schemaforge` package.

**Architecture:** Two MCP servers boot unconfigured and accept live config via token-guarded `POST /config` endpoints (ports 9001/9002). A new `schemaforge_registry` HTTP module (port 9010) owns the derived agent manifest (built from live TrueForge settings) + agent upsert. The UI gains a Settings tab (Models / Connectors / Services / Sandbox / Apply) talking to TrueForge settings API + the registry. A Node CLI (`bin/schemaforge.js`) boots venv + MCP servers + registry + TrueForge + UI with a vite-style proxy.

**Tech Stack:** Python (core registry `http.server`, FastMCP 1.x servers, psycopg, httpx), Node (CLI, vite proxy), React 18.3.1 + Vite (UI), `@truefoundry/trueforge` (server), `schemaforge_core` (engine).

## Global Constraints

- MCP server config endpoint auth: `Authorization: Bearer <SF_MCP_CONFIG_TOKEN>`; env unset → 503 "config disabled".
- MCP servers MUST NOT crash at import when unconfigured; tools raise `RuntimeError("... is not configured: set ... via the Settings panel or POST /config")`.
- Config persistence file: `<state-dir>/postgres-mcp.json`, `<state-dir>/github-mcp.json`, `<state-dir>/agent.json`; state-dir default `~/.schemaforge`, override `SF_STATE_DIR`.
- Registry ports: `SF_CONFIG_PORT` postgres-mcp 9001, github-mcp 9002, `SF_REGISTRY_PORT` 9010; MCP transport ports stay 8001/8002.
- TrueForge settings shapes (live-verified): model-providers upsert `PUT /api/v1/settings/model-providers` `{"manifest": {type:'custom', name, base_url, auth:{api_key}, models:[{model_id,name,properties}]}}`; mcp-servers upsert `PUT /api/v1/settings/mcp-servers` `{"manifest": {type:'remote', name, url, description, auth?}}` + `DELETE /api/v1/settings/mcp-servers/{name}`; sandbox upsert `PUT /api/v1/settings/sandbox-providers` `{"manifest": {type:'daytona', auth:{api_key}, exec_timeout_ms, auto_stop, auto_archive, auto_delete}}`; agents upsert: find by name in `GET /api/v1/agents` then `PUT /api/v1/agents/{id}` `{"manifest": ...}` else `POST /api/v1/agents` `{"name","manifest"}`.
- ResourceName regex: `^[a-z](?:[a-z0-9._-]{0,62}[a-z0-9])$` max 64.
- Agent manifest fixed config: iteration_limit 60, dynamic_sub_agents/generative_ui/ask_user_questions/context_management.compaction/large_tool_response enabled; approval policy by name: postgres-prod → `["@write","@destructive"]`, others → `[]` (UI-overridable); preload true for postgres-prod else false.
- Skill `schemaforge-migration` attached ONLY when `capabilities.sandbox.enabled`.
- Existing test suites must stay green: core 13 tests, UI 24 tests, demo-app 6 tests.
- Each PR Qodo-reviewed (`/agentic_review`) to Bugs(0) before merge; squash-merge + branch delete.

---
# Task 1: Registry manifest builder (pure logic)

**Files:**
- Create: `core/schemaforge_core/registry.py`
- Test: `core/tests/test_registry_manifest.py`

**Interfaces:**
- Consumes: nothing (pure function); TrueForge settings shapes from Global Constraints.
- Produces: `SettingsSnapshot` dataclass, `build_manifest(snapshot, instructions, model_fqn, overrides) -> dict`, `AGENT_NAME`, `APPROVAL_POLICY`, `PRELOAD_SERVERS`, `SKILL`, `ITERATION_LIMIT`, `STATE_DIR`, `load_agent_state()`, `save_agent_state(state)`.

- [ ] **Step 1: Write the failing test**

`core/tests/test_registry_manifest.py`:

```python
from schemaforge_core.registry import (
    APPROVAL_POLICY,
    PRELOAD_SERVERS,
    SKILL,
    SettingsSnapshot,
    build_manifest,
)

INSTRUCTIONS = "You are SchemaForge."


def test_manifest_includes_only_enabled_servers():
    snap = SettingsSnapshot(
        mcp_servers=[
            {"name": "postgres-prod", "url": "http://x/mcp", "description": ""},
            {"name": "github", "url": "http://y/mcp", "description": ""},
        ],
        models=["cloudflare/deepseek-v4-flash"],
        sandbox_enabled=True,
    )
    m = build_manifest(snap, INSTRUCTIONS, model_fqn=None, overrides={})
    names = [s["name"] for s in m["mcp_servers"]]
    assert names == ["postgres-prod", "github"]
    assert m["mcp_servers"][0]["preload"] is True
    assert m["mcp_servers"][0]["require_approval_for_tools"] == ["@write", "@destructive"]
    assert m["mcp_servers"][1]["preload"] is False
    assert m["mcp_servers"][1]["require_approval_for_tools"] == []
    assert m["skills"] == [{"name": SKILL}]
    assert m["config"]["sandbox"]["enabled"] is True
    assert m["config"]["iteration_limit"] == 60


def test_disabled_server_omitted():
    snap = SettingsSnapshot(
        mcp_servers=[{"name": "github", "url": "http://y/mcp", "description": ""}],
        models=["cloudflare/deepseek-v4-flash"],
        sandbox_enabled=False,
    )
    m = build_manifest(snap, INSTRUCTIONS, model_fqn=None, overrides={})
    assert [s["name"] for s in m["mcp_servers"]] == ["github"]
    assert m["skills"] == []
    assert m["config"]["sandbox"]["enabled"] is False


def test_model_selection_precedence():
    snap = SettingsSnapshot(models=["a/one", "b/two"], sandbox_enabled=False)
    assert build_manifest(snap, INSTRUCTIONS, None, {})["model"] == {"name": "a/one"}
    assert build_manifest(snap, INSTRUCTIONS, "b/two", {})["model"] == {"name": "b/two"}
    assert build_manifest(snap, INSTRUCTIONS, None, {"model": "b/two"})["model"] == {"name": "b/two"}


def test_no_model_raises():
    import pytest

    snap = SettingsSnapshot(models=[], sandbox_enabled=False)
    with pytest.raises(RuntimeError):
        build_manifest(snap, INSTRUCTIONS, None, {})


def test_approval_override():
    snap = SettingsSnapshot(
        mcp_servers=[{"name": "github", "url": "http://y/mcp", "description": ""}],
        models=["a/one"],
        sandbox_enabled=False,
    )
    m = build_manifest(snap, INSTRUCTIONS, None, {"github": ["@write"]})
    assert m["mcp_servers"][0]["require_approval_for_tools"] == ["@write"]


def test_policy_constants():
    assert APPROVAL_POLICY["postgres-prod"] == ["@write", "@destructive"]
    assert PRELOAD_SERVERS == {"postgres-prod"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && ../.vevn/bin/python -m pytest tests/test_registry_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schemaforge_core.registry'`

- [ ] **Step 3: Write the implementation**

`core/schemaforge_core/registry.py`:

```python
"""Derived agent manifest builder (single source of truth for agent policy).

The agent spec is DERIVED state: it is built from the live TrueForge
settings (MCP servers, model providers, sandbox) so that nothing is
hardcoded and unconfigured services are simply omitted. The UI Apply
button and the apply_agent.py CLI both call build_manifest().
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

AGENT_NAME = "schemaforge"
APPROVAL_POLICY: dict[str, list[str]] = {"postgres-prod": ["@write", "@destructive"]}
PRELOAD_SERVERS: set[str] = {"postgres-prod"}
SKILL = "schemaforge-migration"
ITERATION_LIMIT = 60
STATE_DIR = os.environ.get("SF_STATE_DIR", os.path.expanduser("~/.schemaforge"))


@dataclass
class SettingsSnapshot:
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    sandbox_enabled: bool = False


def build_manifest(
    snapshot: SettingsSnapshot,
    instructions: str,
    model_fqn: str | None,
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the AgentSpec manifest from live settings. Pure function."""
    overrides = overrides or {}
    model = overrides.get("model") or model_fqn
    if not model and snapshot.models:
        model = snapshot.models[0]
    if not model:
        raise RuntimeError("no model provider configured - add one in Settings first")

    mcp_servers = [
        {
            "name": s["name"],
            "enable_tools": ["@all"],
            "preload": s["name"] in PRELOAD_SERVERS,
            "require_approval_for_tools": overrides.get(
                s["name"], APPROVAL_POLICY.get(s["name"], [])
            ),
        }
        for s in snapshot.mcp_servers
        if s.get("enabled", True)
    ]
    return {
        "model": {"name": model},
        "instructions": instructions,
        "mcp_servers": mcp_servers,
        "skills": [{"name": SKILL}] if snapshot.sandbox_enabled else [],
        "config": {
            "sandbox": {"enabled": snapshot.sandbox_enabled},
            "dynamic_sub_agents": {"enabled": True},
            "generative_ui": {"enabled": True},
            "ask_user_questions": {"enabled": True},
            "iteration_limit": ITERATION_LIMIT,
        },
    }


def load_agent_state() -> dict[str, Any]:
    """Persisted UI selections (model FQN), if any."""
    path = os.path.join(STATE_DIR, "agent.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_agent_state(state: dict[str, Any]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "agent.json"), "w") as f:
        json.dump(state, f)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && ../.vevn/bin/python -m pytest tests/test_registry_manifest.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd /home/utsav/Github/schemaforge
git checkout -b feat/config-first
git add core/schemaforge_core/registry.py core/tests/test_registry_manifest.py
git commit -m "feat(registry): derived agent manifest builder + tests"
```

# Task 2: Registry settings client + HTTP server (sf-registry)

**Files:**
- Create: `core/schemaforge_core/registry_server.py`
- Modify: `core/pyproject.toml` (add script `sf-registry`, add `httpx` dep)
- Test: `core/tests/test_registry_server.py`

**Interfaces:**
- Consumes: `build_manifest`, `load_agent_state`, `save_agent_state`, `AGENT_NAME`, `SettingsSnapshot` from Task 1.
- Produces: `fetch_snapshot(client) -> SettingsSnapshot`, `upsert_agent(client, manifest) -> dict`, `run_server(host, port)`, `main()`; console script `sf-registry`.

- [ ] **Step 1: Write the failing test**

`core/tests/test_registry_server.py` (uses `httpx.MockTransport` - no live server):

```python
import httpx

from schemaforge_core.registry_server import fetch_snapshot, upsert_agent


def _mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_snapshot():
    def handler(request):
        if request.url.path == "/api/v1/settings/mcp-servers":
            return httpx.Response(200, json={"data": [{"name": "github", "url": "http://y/mcp"}]})
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json={"data": [{"name": "cloudflare/deepseek-v4-flash"}]})
        if request.url.path == "/api/v1/capabilities":
            return httpx.Response(200, json={"data": {"sandbox": {"enabled": True}}})
        return httpx.Response(404)

    snap = fetch_snapshot(_mock(handler))
    assert snap.mcp_servers == [{"name": "github", "url": "http://y/mcp"}]
    assert snap.models == ["cloudflare/deepseek-v4-flash"]
    assert snap.sandbox_enabled is True


def test_upsert_agent_existing():
    def handler(request):
        if request.method == "GET" and request.url.path == "/api/v1/agents":
            return httpx.Response(200, json={"data": [{"id": "abc", "name": "schemaforge"}]})
        if request.method == "PUT" and request.url.path == "/api/v1/agents/abc":
            return httpx.Response(200, json={"data": {"id": "abc"}})
        return httpx.Response(500)

    out = upsert_agent(_mock(handler), {"model": {"name": "a/one"}})
    assert out["id"] == "abc"


def test_upsert_agent_creates():
    def handler(request):
        if request.method == "GET" and request.url.path == "/api/v1/agents":
            return httpx.Response(200, json={"data": []})
        if request.method == "POST" and request.url.path == "/api/v1/agents":
            return httpx.Response(200, json={"data": {"id": "new"}})
        return httpx.Response(500)

    out = upsert_agent(_mock(handler), {"model": {"name": "a/one"}})
    assert out["id"] == "new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && ../.vevn/bin/python -m pytest tests/test_registry_server.py -v`
Expected: FAIL `ModuleNotFoundError: registry_server`

- [ ] **Step 3: Write the implementation**

`core/schemaforge_core/registry_server.py`:

```python
"""HTTP registry server (sf-registry, port 9010).

Routes:
  GET  /health           -> {"ok": true}
  GET  /snapshot         -> SettingsSnapshot as JSON (UI status)
  POST /apply-agent      -> {model?: str, overrides?: {server: [approvals]}}
                            builds the manifest from live settings, upserts the
                            agent, returns the manifest
  POST /config           -> {model: "fqn"} persists the UI model selection
All payloads use {"data": ...} envelope like the TrueForge API.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx

from schemaforge_core.registry import (
    AGENT_NAME,
    SettingsSnapshot,
    build_manifest,
    load_agent_state,
    save_agent_state,
)

TRUEFORGE_URL = os.environ.get("TRUEFORGE_URL", "http://localhost:8790")
DEFAULT_PORT = int(os.environ.get("SF_REGISTRY_PORT", "9010"))
_AGENT_INSTRUCTIONS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "agent",
    "instructions.md",
)


def fetch_snapshot(client: httpx.Client) -> SettingsSnapshot:
    servers = client.get(f"{TRUEFORGE_URL}/api/v1/settings/mcp-servers").json().get("data", [])
    models = client.get(f"{TRUEFORGE_URL}/api/v1/models").json().get("data", [])
    caps = client.get(f"{TRUEFORGE_URL}/api/v1/capabilities").json().get("data", {})
    return SettingsSnapshot(
        mcp_servers=[
            {"name": s.get("name"), "url": s.get("url"), "description": s.get("description", "")}
            for s in servers
        ],
        models=[m.get("name") for m in models],
        sandbox_enabled=bool((caps.get("sandbox") or {}).get("enabled")),
    )


def upsert_agent(client: httpx.Client, manifest: dict[str, Any]) -> dict[str, Any]:
    existing = None
    for a in client.get(f"{TRUEFORGE_URL}/api/v1/agents").json().get("data", []):
        if a.get("name") == AGENT_NAME:
            existing = a
            break
    if existing:
        r = client.put(f"{TRUEFORGE_URL}/api/v1/agents/{existing['id']}", json={"manifest": manifest})
    else:
        r = client.post(f"{TRUEFORGE_URL}/api/v1/agents", json={"name": AGENT_NAME, "manifest": manifest})
    if r.status_code >= 400:
        raise RuntimeError(f"agent upsert failed: {r.status_code} {r.text[:200]}")
    return r.json().get("data", {})


def _instructions() -> str:
    with open(_AGENT_INSTRUCTIONS_PATH) as f:
        return f.read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, obj: Any) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            return self._send(200, {"data": {"ok": True}})
        if self.path == "/snapshot":
            with httpx.Client(timeout=30) as c:
                snap = fetch_snapshot(c)
            return self._send(200, {"data": snap.__dict__})
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "invalid JSON"})
        if self.path == "/apply-agent":
            try:
                with httpx.Client(timeout=60) as c:
                    snap = fetch_snapshot(c)
                    state = load_agent_state()
                    manifest = build_manifest(
                        snap, _instructions(), state.get("model"), body.get("overrides", {})
                    )
                    upsert_agent(c, manifest)
                return self._send(
                    200,
                    {"data": {"manifest": manifest, "omitted": [s["name"] for s in snap.mcp_servers if not s.get("enabled", True)]}},
                )
            except Exception as exc:
                return self._send(422, {"error": str(exc)})
        if self.path == "/config":
            model = body.get("model")
            if not model:
                return self._send(400, {"error": "model required"})
            save_agent_state({"model": model})
            return self._send(200, {"data": {"model": model}})
        self._send(404, {"error": "not found"})


def run_server(host: str = "127.0.0.1", port: int | None = None) -> None:
    port = port or DEFAULT_PORT
    print(f"sf-registry on {host}:{port} -> TrueForge {TRUEFORGE_URL}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main() -> None:
    run_server(host=os.environ.get("SF_REGISTRY_HOST", "127.0.0.1"))


if __name__ == "__main__":
    main()
```

`core/pyproject.toml` - add `httpx>=0.27` to `dependencies` and `sf-registry = "schemaforge_core.registry_server:main"` to `[project.scripts]`.

- [ ] **Step 4: Run tests + smoke the server**

Run: `cd core && ../.vevn/bin/python -m pytest tests/ -v`
Expected: 13 existing + 3 new = 16 passed

Smoke (needs the live local TrueForge on [::1]:8790):
```bash
cd /home/utsav/Github/schemaforge
SF_REGISTRY_PORT=19010 .vevn/bin/python -m schemaforge_core.registry_server &
```
Then probe `http://127.0.0.1:19010/health` and `/snapshot` with a short Python httpx script (no curl). Expect `{"data": {"ok": true}}` and the live settings snapshot. Kill the process.

- [ ] **Step 5: Commit**

```bash
git add core/
git commit -m "feat(registry): settings client + sf-registry HTTP server (health/snapshot/apply-agent/config)"
```

# Task 3: postgres-mcp lazy config + /config endpoint

**Files:**
- Modify: `mcp-servers/postgres-mcp/server.py` (lazy DSN, config holder, HTTP config server, `SF_CONFIG_PORT`)
- Test: `mcp-servers/postgres-mcp/test_config.py`

**Interfaces:**
- Consumes: env `SF_MCP_CONFIG_TOKEN`, `SF_CONFIG_PORT` (default 9001), `SF_STATE_DIR`.
- Produces: `POST /config` `{"database_url": ...}` on port 9001 (bearer token); `GET /config` → `{"configured": bool}`; tools raise `RuntimeError("postgres-prod is not configured: set a DATABASE_URL via the Settings panel or POST /config")` when unset.

- [ ] **Step 1: Write the failing test**

`mcp-servers/postgres-mcp/test_config.py`:

```python
"""Tests for the lazy-config behavior (no real DB needed)."""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

# The server module must be importable without DATABASE_URL set.
os.environ.pop("DATABASE_URL", None)
os.environ["SF_MCP_CONFIG_TOKEN"] = "test-token"
os.environ["SF_CONFIG_PORT"] = "19001"
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mcp-servers/postgres-mcp && ../../.vevn/bin/python -m pytest test_config.py -v`
Expected: FAIL (`run_config_server` missing, `_conn` missing)

- [ ] **Step 3: Write the implementation**

Edit `mcp-servers/postgres-mcp/server.py`:

Replace the top (currently):
```python
DSN = os.environ["DATABASE_URL"]
```
with:
```python
STATE_DIR = os.environ.get("SF_STATE_DIR", os.path.expanduser("~/.schemaforge"))
_config: dict = _load_config()
_CONFIG_TOKEN = os.environ.get("SF_MCP_CONFIG_TOKEN")
CONFIG_PORT = int(os.environ.get("SF_CONFIG_PORT", "9001"))
_config_httpd = None


def _load_config() -> dict:
    path = os.path.join(STATE_DIR, "postgres-mcp.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    dsn = os.environ.get("DATABASE_URL")
    return {"database_url": dsn}


def _save_config() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "postgres-mcp.json"), "w") as f:
        json.dump(_config, f)
```

Replace `_conn()` (currently `return psycopg.connect(DSN, ...)`) with:
```python
def _conn() -> psycopg.Connection:
    dsn = _config.get("database_url")
    if not dsn:
        raise RuntimeError(
            "postgres-prod is not configured: set a DATABASE_URL via the Settings panel or POST /config"
        )
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=True)
```

Add a config HTTP server (stdlib, so no new deps). Append before the `if __name__ == "__main__":` block:

```python
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ConfigHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not _CONFIG_TOKEN:
            self._send(503, {"error": "config disabled: SF_MCP_CONFIG_TOKEN unset"})
            return False
        if self.headers.get("Authorization") != f"Bearer {_CONFIG_TOKEN}":
            self._send(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:
        if self.path == "/config":
            return self._send(200, {"data": {"configured": bool(_config.get("database_url"))}})
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/config":
            return self._send(404, {"error": "not found"})
        if not self._authorized():
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "invalid JSON"})
        dsn = body.get("database_url")
        if not dsn or not dsn.startswith(("postgresql://", "postgres://")):
            return self._send(400, {"error": "database_url must be a postgresql:// DSN"})
        _config["database_url"] = dsn
        _save_config()
        return self._send(202, {"data": {"ok": True, "configured": True}})


def run_config_server(host: str = "127.0.0.1") -> None:
    global _config_httpd
    _config_httpd = ThreadingHTTPServer((host, CONFIG_PORT), ConfigHandler)
    print(f"postgres-mcp config endpoint on {host}:{CONFIG_PORT}")
    _config_httpd.serve_forever()
```

(Add `import json` at the top.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd mcp-servers/postgres-mcp && ../../.vevn/bin/python -m pytest test_config.py -v`
Expected: 4 passed

Also verify existing behavior unchanged: the server still boots and MCP initialize works when DATABASE_URL is set (use the 8011-container smoke pattern from Task 9 if desired; or skip — the change is additive).

- [ ] **Step 5: Commit**

```bash
cd /home/utsav/Github/schemaforge
git add mcp-servers/postgres-mcp/server.py mcp-servers/postgres-mcp/test_config.py
git commit -m "feat(postgres-mcp): lazy DSN config + token-guarded POST /config endpoint"
```

# Task 4: github-mcp lazy config + /config endpoint

**Files:**
- Modify: `mcp-servers/github-mcp/server.py` (lazy token, default_repo, config HTTP server, `SF_CONFIG_PORT`)
- Test: `mcp-servers/github-mcp/test_config.py`

**Interfaces:**
- Consumes: env `SF_MCP_CONFIG_TOKEN`, `SF_CONFIG_PORT` (default 9002), `SF_STATE_DIR`.
- Produces: `POST /config` `{"token": ..., "default_repo": ...}` on port 9002 (bearer token); `GET /config` → `{"configured": bool}`; tools default `repo` to `default_repo` when the arg is empty; `_client()` raises `RuntimeError("github is not configured: set a token via the Settings panel or POST /config")` when token unset.

- [ ] **Step 1: Write the failing test**

`mcp-servers/github-mcp/test_config.py`:

```python
"""Tests for the lazy-config behavior (no network calls)."""
import os
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

os.environ.pop("GITHUB_PERSONAL_ACCESS_TOKEN", None)
os.environ["SF_MCP_CONFIG_TOKEN"] = "test-token"
os.environ["SF_CONFIG_PORT"] = "19002"
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mcp-servers/github-mcp && ../../.vevn/bin/python -m pytest test_config.py -v`
Expected: FAIL

- [ ] **Step 3: Write the implementation**

Edit `mcp-servers/github-mcp/server.py`:

Replace the top (currently):
```python
TOKEN = os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"]
API = "https://api.github.com"
_HEADERS = {...}
```
with:
```python
API = "https://api.github.com"
STATE_DIR = os.environ.get("SF_STATE_DIR", os.path.expanduser("~/.schemaforge"))
_config: dict = _load_config()
_CONFIG_TOKEN = os.environ.get("SF_MCP_CONFIG_TOKEN")
CONFIG_PORT = int(os.environ.get("SF_CONFIG_PORT", "9002"))
_config_httpd = None


def _load_config() -> dict:
    path = os.path.join(STATE_DIR, "github-mcp.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"token": os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN"), "default_repo": None}


def _save_config() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "github-mcp.json"), "w") as f:
        json.dump(_config, f)


def _resolve_repo(repo: str) -> str:
    return repo or _config.get("default_repo") or ""
```

Replace `_client()` with:
```python
def _client() -> httpx.Client:
    token = _config.get("token")
    if not token:
        raise RuntimeError(
            "github is not configured: set a token via the Settings panel or POST /config"
        )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    return httpx.Client(headers=headers, timeout=60)
```

Each tool: replace `def get_repo(repo: str) -> dict:` with `def get_repo(repo: str = "") -> dict:` and `repo = _resolve_repo(repo)` as the first line. Do the same for `branch_exists`, `create_branch`, `write_file`, `open_pull_request` (keep other params unchanged; `repo` becomes `str = ""` in each signature). If `repo` is still empty after resolution, `raise ValueError("no repo: pass repo or set default_repo via POST /config")`.

Add the same ConfigHandler / `run_config_server` as Task 3 (port default 9002), accepting `{"token": ..., "default_repo": ...}` — at least one must be present; token must start with `ghp_`/`github_pat_`/`gho_`/`ghu_` (400 otherwise). Persist via `_save_config()`.

(Add `import json` at the top.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd mcp-servers/github-mcp && ../../.vevn/bin/python -m pytest test_config.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd /home/utsav/Github/schemaforge
git add mcp-servers/github-mcp/server.py mcp-servers/github-mcp/test_config.py
git commit -m "feat(github-mcp): lazy token/repo config + token-guarded POST /config endpoint"
```

# Task 5: Conditional agent instructions (graceful degradation)

**Files:**
- Modify: `agent/instructions.md`
- Modify: `skills/schemaforge-migration/SKILL.md` (the Steps that hardcode github/repo)

**Interfaces:**
- Consumes: the derived-manifest model from Tasks 1-2 (mcp servers may be absent).
- Produces: instructions that tell the agent to detect which MCP servers are attached (via `list_tools` / presence of the server) and skip unconfigured steps instead of crashing.

- [ ] **Step 1: Rewrite the hardcoded sections of `agent/instructions.md`**

Replace the "## Tool inventory" section with a conditional one:

```markdown
## Tool inventory (detect at runtime — some servers may be absent)

The MCP servers attached to this agent are a DERIVED set: only the ones the
operator configured. Before relying on a server, confirm it is present (its
tools appear in your tool list). NEVER call a tool from a server you cannot
see — that fails. Missing servers are a config choice, not an error.

- `postgres-prod` MCP (IF present): `list_tables`, `table_schema`, `row_count`,
  `explain` (read-only); `execute_ddl` and `execute_migration` (both
  APPROVAL-GATED — the only irreversible steps). If ABSENT: skip all prod-DB
  introspection and the prod apply; deliver the migration SQL + verify against
  the sandbox DB only, and say clearly "production apply skipped: no
  postgres-prod MCP configured".
- `github` MCP (IF present): repo/branch/file/PR tools (reversible — not
  gated). If ABSENT: skip the PR step; save the diff as an artifact
  (`out/diff.patch` via the sandbox) and say "PR skipped: no github MCP
  configured".
- Sandbox (Code Mode): python + `schemaforge_core` + `demo-app` checkout at
  `/workspace`. If the sandbox capability is disabled, do not attempt shell
  steps; explain what could not be verified.
- Skill `schemaforge-migration`: the step-by-step workflow. Follow it.
```

Replace the "## Workflow" step 8 with a conditional one:

```markdown
8. Open the GitHub PR — ONLY IF the `github` MCP server is present. Push the
   modified files (migration + code) to a new branch `schemaforge/<slug>` via
   the github MCP and create the PR with a description that embeds the safety
   report and the impact graph. Otherwise write `git diff > /workspace/out/diff.patch`
   in the sandbox and report the artifact path instead of a PR URL.
```

Also replace the two hardcoded repo references: `git clone --depth 1
https://github.com/ronakgupta03/schemaforge.git /workspace` becomes
`git clone --depth 1 <GITHUB_REPO_URL> /workspace` with a preceding line
"`GITHUB_REPO_URL` (default `https://github.com/ronakgupta03/schemaforge.git`)
is available in the sandbox environment; clone that." — and note in the
bootstrap that the operator may have pointed SchemaForge at a different repo.

- [ ] **Step 2: Mirror the conditional steps in `skills/schemaforge-migration/SKILL.md`**

In SKILL.md, the "Open PR" step and any "use github MCP" lines get the same
IF-present guard: "If the github MCP server is attached, open the PR...;
otherwise save `git diff > /workspace/out/diff.patch` and report the artifact."
The verify step keeps its hard requirement (verify MUST run when the sandbox
is available).

- [ ] **Step 3: Verify no remaining hardcoded repo/tool assumptions**

Run: `grep -n "ronakgupta03" agent/instructions.md skills/schemaforge-migration/SKILL.md | head`
Expected: only the "default" mention of the repo URL in instructions.md (the
clone line may keep the default repo URL as the documented default), zero
unconditional "must use github" phrasing.

- [ ] **Step 4: Commit**

```bash
git add agent/instructions.md skills/schemaforge-migration/SKILL.md
git commit -m "feat(instructions): conditional MCP usage — skip unconfigured servers gracefully"
```

# Task 6: apply_agent.py becomes a thin builder wrapper

**Files:**
- Modify: `scripts/apply_agent.py`

**Interfaces:**
- Consumes: `build_manifest`, `SettingsSnapshot`, `upsert_agent`, `load_agent_state` from `schemaforge_core.registry(_server)` (Tasks 1-2).
- Produces: CLI that reads live settings (not hardcoded lists), applies `SCHEMAFORGE_MODEL` env or persisted agent state, and upserts the agent. Prints the manifest JSON.

- [ ] **Step 1: Write the replacement**

Replace the body of `scripts/apply_agent.py` with:

```python
"""Create/update the 'schemaforge' agent from LIVE TrueForge settings.

Nothing here is hardcoded: the manifest is derived from the configured MCP
servers, model providers, and sandbox capability. CLI usage:
    TRUEFORGE_URL=http://localhost:8790 .vevn/bin/python scripts/apply_agent.py
Env: SCHEMAFORGE_MODEL (optional override for the model FQN).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

from schemaforge_core.registry import load_agent_state
from schemaforge_core.registry_server import fetch_snapshot, upsert_agent
from schemaforge_core.registry import build_manifest

BASE = os.environ.get("TRUEFORGE_URL", "http://localhost:8790")
HERE = Path(__file__).resolve().parent
INSTRUCTIONS = (HERE.parent / "agent" / "instructions.md").read_text()


def main() -> None:
    model = os.environ.get("SCHEMAFORGE_MODEL") or load_agent_state().get("model")
    with httpx.Client(base_url=BASE, timeout=60) as client:
        snapshot = fetch_snapshot(client)
        manifest = build_manifest(snapshot, INSTRUCTIONS, model, overrides=None)
        result = upsert_agent(client, manifest)
    print(json.dumps({"agent": result, "manifest": manifest}, indent=2))
    omitted = [s["name"] for s in snapshot.mcp_servers if not s.get("enabled", True)]
    if omitted:
        print(f"note: disabled/absent servers omitted: {omitted}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

Note: `fetch_snapshot`/`upsert_agent` in Task 2 read `TRUEFORGE_URL` from the module env at import — they must use the `BASE` value here. Edit `registry_server.py` to accept a `base_url` argument defaulting to `TRUEFORGE_URL`: `def fetch_snapshot(client, base_url=TRUEFORGE_URL)` and `def upsert_agent(client, manifest, base_url=TRUEFORGE_URL)`, using `f"{base_url}/api/..."` internally. Update the Task 2 tests accordingly (they already pass base-less calls; the default keeps them green).

- [ ] **Step 2: Verify the CLI runs against the live local TrueForge**

Run: `cd /home/utsav/Github/schemaforge && TRUEFORGE_URL=http://localhost:8790 .vevn/bin/python scripts/apply_agent.py`
Expected: prints the agent + manifest derived from the live local settings (the local harness has cloudflare provider + postgres-prod + github configured, so the manifest should include both servers and the cloudflare model — same as before, but now derived).

- [ ] **Step 3: Commit**

```bash
git add scripts/apply_agent.py core/schemaforge_core/registry_server.py core/tests/test_registry_server.py
git commit -m "refactor(apply_agent): derive manifest from live settings via registry builder"
```

# Task 7: UI settings API client + Settings tab

**Files:**
- Create: `ui/src/settingsApi.ts`
- Create: `ui/src/components/SettingsPanel.tsx`
- Modify: `ui/src/components/EvidencePanel.tsx` (add 6th tab "Settings")
- Modify: `ui/vite.config.ts` (proxy `/api/sf/*` → registry + MCP config ports)
- Test: `ui/src/components/SettingsPanel.test.tsx`

**Interfaces:**
- Consumes: TrueForge settings endpoints (Global Constraints), registry endpoints (Task 2), MCP config endpoints (Tasks 3-4).
- Produces: `settingsApi.ts` functions: `listModelProviders`, `listModels`, `upsertModelProvider`, `deleteModelProvider`, `listMcpServers`, `upsertMcpServer`, `deleteMcpServer`, `getCapabilities`, `upsertSandboxProvider`, `registryHealth`, `registrySnapshot`, `registryApplyAgent`, `registrySetModel`, `configPostgres`, `configGithub` — all taking `(fetchFn, ...)` like `sfApi.ts`.

- [ ] **Step 1: Write the failing test**

`ui/src/components/SettingsPanel.test.tsx` (mock fetch; assert the tab renders sections and Apply calls the registry):

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { SettingsPanel } from "./SettingsPanel";

const ok = (body: unknown) => ({ ok: true, json: async () => body }) as Response;

function mockFetch(overrides: Record<string, () => Promise<Response>>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    for (const [prefix, fn] of Object.entries(overrides)) {
      if (url.startsWith(prefix)) return fn();
    }
    return ok({ data: [] });
  });
}

test("renders five sections and live status", async () => {
  const fetchFn = mockFetch({
    "/api/v1/settings/mcp-servers": async () => ok({ data: [{ name: "github", url: "http://y/mcp" }] }),
    "/api/v1/models": async () => ok({ data: [{ name: "cloudflare/deepseek-v4-flash" }] }),
    "/api/v1/capabilities": async () => ok({ data: { sandbox: { enabled: true } } }),
    "/api/sf/snapshot": async () => ok({ data: { mcp_servers: [{ name: "github" }], models: ["cloudflare/deepseek-v4-flash"], sandbox_enabled: true } }),
  });
  render(<SettingsPanel fetchFn={fetchFn} />);
  expect(await screen.findByText("Models")).toBeInTheDocument();
  expect(screen.getByText("Connectors")).toBeInTheDocument();
  expect(screen.getByText("Services")).toBeInTheDocument();
  expect(screen.getByText("Sandbox")).toBeInTheDocument();
  expect(screen.getByText("Apply agent")).toBeInTheDocument();
  expect(screen.getByText("cloudflare/deepseek-v4-flash")).toBeInTheDocument();
});

test("Apply button posts to the registry and shows the manifest", async () => {
  const fetchFn = mockFetch({
    "/api/sf/apply-agent": async () => ok({ data: { manifest: { model: { name: "x" } }, omitted: [] } }),
  });
  render(<SettingsPanel fetchFn={fetchFn} />);
  fireEvent.click(await screen.findByText("Save & apply agent"));
  expect(await screen.findByText(/manifest applied/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/components/SettingsPanel.test.tsx`
Expected: FAIL (`SettingsPanel` missing)

- [ ] **Step 3: Write the implementation**

`ui/src/settingsApi.ts` — thin wrappers over `fetchFn` (pattern of `sfApi.ts`):

```ts
import type { FetchFn } from "./sfApi";

const json = async <T>(res: Response): Promise<T> => {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
};

export const listModelProviders = (f: FetchFn) => json<{ data: unknown[] }>(await f("/api/v1/settings/model-providers")).then((b) => b.data ?? []);
export const listModels = (f: FetchFn) => json<{ data: { name: string }[] }>(await f("/api/v1/models")).then((b) => b.data ?? []);
export const upsertModelProvider = (f: FetchFn, manifest: unknown) => f("/api/v1/settings/model-providers", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ manifest }) });
export const deleteModelProvider = (f: FetchFn, name: string) => f(`/api/v1/settings/model-providers/${encodeURIComponent(name)}`, { method: "DELETE" });
export const listMcpServers = (f: FetchFn) => json<{ data: unknown[] }>(await f("/api/v1/settings/mcp-servers")).then((b) => b.data ?? []);
export const upsertMcpServer = (f: FetchFn, manifest: unknown) => f("/api/v1/settings/mcp-servers", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ manifest }) });
export const deleteMcpServer = (f: FetchFn, name: string) => f(`/api/v1/settings/mcp-servers/${encodeURIComponent(name)}`, { method: "DELETE" });
export const getCapabilities = (f: FetchFn) => json<{ data: { sandbox?: { enabled?: boolean } } }>(await f("/api/v1/capabilities")).then((b) => b.data);
export const upsertSandboxProvider = (f: FetchFn, manifest: unknown) => f("/api/v1/settings/sandbox-providers", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ manifest }) });
export const registryHealth = (f: FetchFn) => json<{ data: { ok: boolean } }>(await f("/api/sf/health")).then((b) => b.data);
export const registrySnapshot = (f: FetchFn) => json<{ data: { mcp_servers: unknown[]; models: string[]; sandbox_enabled: boolean } }>(await f("/api/sf/snapshot")).then((b) => b.data);
export const registryApplyAgent = (f: FetchFn, overrides: Record<string, string[]> = {}) => f("/api/sf/apply-agent", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ overrides }) });
export const registrySetModel = (f: FetchFn, model: string) => f("/api/sf/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }) });
export const configPostgres = (f: FetchFn, databaseUrl: string) => f("/api/sf/config/postgres-mcp", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ database_url: databaseUrl }) });
export const configGithub = (f: FetchFn, token: string, defaultRepo: string) => f("/api/sf/config/github-mcp", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, default_repo: defaultRepo }) });
```

Note: `async` functions must not be used where a plain `(f) => f(...)` returns a Promise — keep each wrapper's return type consistent (the `json` helper already awaits; remove the erroneous `await` prefixes from the arrow bodies — write them as `(f) => json(...)`). The implementer should match `sfApi.ts`'s plain style.

`ui/src/components/SettingsPanel.tsx` — a tab component with the five sections; each section fetches on mount via the passed `fetchFn` (default `fetch`), holds local form state, and calls the API functions on submit. Apply shows the returned manifest summary or the error from the 422 body. Keep styling consistent with the other panels (section headings, `var(--sf-border)` borders).

`ui/src/components/EvidencePanel.tsx` — add `"Settings"` to the tab list and render `<SettingsPanel fetchFn={fetch} />` for it (the panel already owns the tab switch).

`ui/vite.config.ts` — add proxy entries (order matters: specific paths first):

```ts
proxy: {
  "/api/sf/config/postgres-mcp": { target: "http://127.0.0.1:9001", changeOrigin: false },
  "/api/sf/config/github-mcp": { target: "http://127.0.0.1:9002", changeOrigin: false },
  "/api/sf": { target: "http://127.0.0.1:9010", changeOrigin: false },
  "/api": { target: "http://[::1]:8790", changeOrigin: false },
},
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ui && npx vitest run`
Expected: 24 existing + 2 new = 26 passed

Run: `cd ui && npm run build` — Expected: 0 errors (tsc + vite).

- [ ] **Step 5: Commit**

```bash
git add ui/src/settingsApi.ts ui/src/components/SettingsPanel.tsx ui/src/components/SettingsPanel.test.tsx ui/src/components/EvidencePanel.tsx ui/vite.config.ts
git commit -m "feat(ui): Settings tab — models, connectors, services, sandbox, apply agent"
```

# Task 8: npx package `@schemaforge/schemaforge`

**Files:**
- Create: `packages/cli/package.json`
- Create: `packages/cli/bin/schemaforge.js`
- Create: `packages/cli/README.md`
- Modify: repo `.gitignore` (ignore `packages/cli/ui-dist`, `packages/cli/.sfenv`)

**Interfaces:**
- Consumes: built `ui/dist`, `mcp-servers/*` sources, `core/` sources, `agent/instructions.md`, `skills/schemaforge-migration/`, `scripts/sandbox_setup.sh`, the registry (Task 2), MCP config endpoints (Tasks 3-4), `@truefoundry/trueforge` server.
- Produces: `npx @schemaforge/schemaforge` boots the full local stack; `--no-open`, `--port`, `--state-dir` flags.

- [ ] **Step 1: Write the package manifest**

`packages/cli/package.json`:

```json
{
  "name": "@schemaforge/schemaforge",
  "version": "0.1.0",
  "description": "SchemaForge — config-first autonomous DB migration agent (TrueForge harness + MCP servers + evidence UI)",
  "type": "module",
  "bin": { "schemaforge": "bin/schemaforge.js" },
  "files": [
    "bin/",
    "ui-dist/",
    "mcp-servers/",
    "core/",
    "agent/",
    "skills/",
    "scripts/"
  ],
  "engines": { "node": ">=20" },
  "scripts": {
    "build": "cd ../../ui && npm run build && rm -rf ../packages/cli/ui-dist && cp -r dist ../packages/cli/ui-dist"
  }
}
```

- [ ] **Step 2: Write the CLI**

`packages/cli/bin/schemaforge.js` (Node 20+, no deps beyond node built-ins; spawns python via child_process):

```js
#!/usr/bin/env node
// SchemaForge local stack: TrueForge + postgres-mcp + github-mcp + registry + UI.
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import { join, dirname, extname, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { once } from "node:events";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const noOpen = args.includes("--no-open");
const uiPort = Number(args[args.indexOf("--port") + 1] ?? 5173);
const stateDir = args[args.indexOf("--state-dir") + 1] ?? join(process.env.HOME ?? ".", ".schemaforge");
const py = process.env.SF_PYTHON ?? "python3";

const kids = [];
function start(cmd, cwd, env) {
  const p = spawn(cmd, { cwd, env: { ...process.env, SF_STATE_DIR: stateDir, ...env }, shell: false, stdio: ["ignore", "inherit", "inherit"] });
  kids.push(p);
  return p;
}

// 1. venv bootstrap (first run)
const venvPy = join(stateDir, ".sfenv", "bin", "python");
if (!existsSync(venvPy)) {
  console.log("[schemaforge] bootstrapping python venv at", join(stateDir, ".sfenv"));
  spawn(py, ["-m", "venv", join(stateDir, ".sfenv")], { stdio: "inherit" });
  const pip = spawn(join(stateDir, ".sfenv", "bin", "pip"), ["install", "-q", "-e", join(ROOT, "core"), "-r", join(ROOT, "mcp-servers/postgres-mcp/requirements.txt"), "-r", join(ROOT, "mcp-servers/github-mcp/requirements.txt")], { stdio: "inherit" });
  await once(pip, "exit");
}

// 2. services
start(venvPy, [join(ROOT, "mcp-servers/postgres-mcp/server.py")], { SF_CONFIG_PORT: "9001", PORT: "8001" });
start(venvPy, [join(ROOT, "mcp-servers/github-mcp/server.py")], { SF_CONFIG_PORT: "9002", PORT: "8002" });
start(venvPy, ["-m", "schemaforge_core.registry_server"], { SF_REGISTRY_PORT: "9010", TRUEFORGE_URL: "http://localhost:8790" });

// 3. TrueForge (standalone)
start("npx", ["@truefoundry/trueforge"], { STANDALONE: "true", PORT: "8790", HOST: "127.0.0.1" });

// 4. static UI + proxy
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".map": "application/json" };
const DIST = join(ROOT, "ui-dist");
const backend = { host: "::1", port: 8790 };
const proxyTargets = [
  { prefix: "/api/sf/config/postgres-mcp", port: 9001 },
  { prefix: "/api/sf/config/github-mcp", port: 9002 },
  { prefix: "/api/sf", port: 9010 },
  { prefix: "/api", port: 8790 },
];
createServer((req, res) => {
  const p = decodeURIComponent((req.url ?? "/").split("?")[0]);
  for (const t of proxyTargets) {
    if (p.startsWith(t.prefix)) {
      const up = require("node:http").request({ host: "127.0.0.1", port: t.port, path: req.url, method: req.method, headers: req.headers }, (r) => { res.writeHead(r.statusCode ?? 502, r.headers); r.pipe(res); });
      up.on("error", () => { if (!res.headersSent) res.writeHead(502); res.end(); });
      req.pipe(up);
      return;
    }
  }
  let file = normalize(join(DIST, p === "/" ? "index.html" : p));
  if (!file.startsWith(DIST)) { res.writeHead(403); res.end(); return; }
  if (!existsSync(file) || statSync(file).isDirectory()) file = join(DIST, "index.html");
  res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream" });
  createReadStream(file).pipe(res);
}).listen(uiPort, "127.0.0.1", () => {
  console.log(`[schemaforge] UI at http://localhost:${uiPort} (TrueForge 8790, registry 9010, mcp 8001/8002)`);
  if (!noOpen) spawn("xdg-open", [`http://localhost:${uiPort}`], { stdio: "ignore" });
});

for (const k of kids) k.on("exit", () => process.exit(0));
```

(Implementer: convert `start` to accept argv arrays; the sketch uses positional args — use `start(py, [args...])` consistently. Add `import { request } from "node:http"` instead of `require`.)

- [ ] **Step 3: Build the package and smoke it**

```bash
cd ui && npm run build
cd ../packages/cli && rm -rf ui-dist && cp -r ../../ui/dist ui-dist
npm pack --dry-run   # confirm bundled files
```

Then a full smoke against an ephemeral state dir:
```bash
cd /tmp && rm -rf sf-smoke && mkdir sf-smoke && cd sf-smoke
node /home/utsav/Github/schemaforge/packages/cli/bin/schemaforge.js --no-open --port 5199 --state-dir /tmp/sf-smoke/state &
```
Wait for readiness, then probe (via a small Node https/http script or the browser tool): `http://127.0.0.1:5199/api/v1/capabilities` (200, sandbox disabled), `http://127.0.0.1:5199/api/sf/health` (200 ok), `http://127.0.0.1:5199/` (SPA index), and confirm `http://127.0.0.1:5199/api/sf/snapshot` shows the empty-settings snapshot. Kill all spawned processes afterwards (they are children of the CLI; killing the CLI's process group suffices: `pkill -f schemaforge.js`).

- [ ] **Step 4: Commit**

```bash
cd /home/utsav/Github/schemaforge
git add packages/cli .gitignore
git commit -m "feat(package): npx @schemaforge/schemaforge — boots TrueForge + MCP servers + registry + UI"
```
# Task 9: Rework deploy PR #22 for config-first

**Files:**
- Modify: `deploy/src/index.ts` (registry container + `/api/sf/*` routing)
- Modify: `deploy/wrangler.toml` (registry container, no MCP envVars)
- Modify: `deploy/Dockerfile.postgres-mcp`, `deploy/Dockerfile.github-mcp` (remove hardcoded env; rely on `/config`)
- Create: `deploy/Dockerfile.registry`
- Modify: `scripts/register_deployed.py` (use registry apply-agent instead of hardcoded manifests)
- Modify: `scripts/apply-cf-secrets.sh` (SF_MCP_CONFIG_TOKEN; drop MCP DSN/token secrets)
- Modify: `deploy/README.md`

**Interfaces:**
- Consumes: registry (Task 2), MCP `/config` (Tasks 3-4), Settings tab routing (Task 7).
- Produces: deployed stack where judges configure everything in the UI; containers boot unconfigured.

- [ ] **Step 1: Add the registry container to the Worker**

In `deploy/src/index.ts`:
- Add `RegistryContainer extends Container` (`defaultPort = 9010`, `sleepAfter = "10m"`, `envVars = { TRUEFORGE_URL: "http://trueforge.internal", SF_REGISTRY_PORT: "9010", SF_REGISTRY_HOST: "0.0.0.0" }`). Registry reaches TrueForge via `trueforge.internal` — add `outboundByHost = { "trueforge.internal": (req, e) => getContainerStub((e as any).TRUEFORGE_CONTAINER, "default").fetch(req) }`.
- Extend the fetch router: `/api/sf/config/postgres-mcp` -> `POSTGRES_MCP_CONTAINER` (default port 9001), `/api/sf/config/github-mcp` -> `GITHUB_MCP_CONTAINER` (9002), `/api/sf/*` -> `REGISTRY_CONTAINER` (9010). Keep the existing `/tf/`, `/assets/`, `/monacoeditorwork/`, `/api/` routes.
- Remove `DATABASE_URL` and `GITHUB_PERSONAL_ACCESS_TOKEN` from the MCP container `envVars` (config arrives via `/config`); keep `PORT: "80"` (outbound interception) and add `SF_MCP_CONFIG_TOKEN: runtimeEnv.SF_MCP_CONFIG_TOKEN` + `SF_CONFIG_PORT: "9001"/"9002"`.

- [ ] **Step 2: Update wrangler.toml**

Add:
```toml
[[containers]]
class_name = "RegistryContainer"
image = "./Dockerfile.registry"
image_build_context = "../"
max_instances = 1
instance_type = "lite"

[[durable_objects.bindings]]
name = "REGISTRY_CONTAINER"
class_name = "RegistryContainer"
```
Add `RegistryContainer` to `new_sqlite_classes` in the `[[migrations]]` block.

- [ ] **Step 3: Write the registry Dockerfile + adjust MCP Dockerfiles**

`deploy/Dockerfile.registry`:
```dockerfile
FROM python:3.12-slim
WORKDIR /srv
COPY core/ ./core/
RUN pip install --no-cache-dir -e ./core
ENV SF_REGISTRY_HOST=0.0.0.0 SF_REGISTRY_PORT=9010 TRUEFORGE_URL=http://trueforge.internal
EXPOSE 9010
CMD ["sf-registry"]
```
`deploy/Dockerfile.postgres-mcp` / `deploy/Dockerfile.github-mcp`: confirm no baked-in credential ENV lines remain (config comes from envVars + `/config`). Confirm the images still build.

- [ ] **Step 4: Rework register_deployed.py**

Replace the hardcoded MCP-servers/model-provider PUTs with a single call to the registry: `POST {TRUEFORGE_URL}/api/sf/apply-agent` (through the Worker origin). Keep `import_skill.py` for the skill. MCP servers are attached to the agent ONLY when the operator configures them in the UI Connectors section (URLs `http://postgres-mcp.internal/mcp` / `http://github-mcp.internal/mcp`).

- [ ] **Step 5: Update apply-cf-secrets.sh**

Secrets now: `POSTGRES_USER/PASSWORD/HOST/PORT/DB` (TrueForge metadata), `REDIS_URL`, `PUBLIC_BASE_URL`, `SF_MCP_CONFIG_TOKEN` (generate: `openssl rand -hex 24`), `DAYTONA_API_KEY`, `CLOUDFLARE_AUTH_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`. Drop `GITHUB_PERSONAL_ACCESS_TOKEN` from deploy secrets (UI-configured now).

- [ ] **Step 6: Update deploy/README.md**

Document: containers boot unconfigured; judges configure models/connectors/services/sandbox in the deployed UI (same Settings tab as local); Apply regenerates the agent; secrets list per Step 5.

- [ ] **Step 7: Verify + commit**

Run: `cd deploy && npx tsc --noEmit` (0 errors); `npx wrangler deploy --dry-run` (config accepted). Push the rework onto `feat/cf-deploy` (PR #22), trigger `/agentic_review`, fix findings to Bugs(0), merge.

```bash
cd /home/utsav/Github/schemaforge
git add deploy/ scripts/
git commit -m "feat(deploy): config-first containers — registry container, /api/sf routing, UI-driven secrets"
git push origin feat/cf-deploy
```

# Task 10: E2E config-first verification + docs

**Files:**
- Modify: `README.md` (npx quickstart + config-first section)
- Modify: `docs/demo-script.md` (if the demo flow changed)

**Interfaces:**
- Consumes: all prior tasks.

- [ ] **Step 1: Live end-to-end (local)**

1. Boot the full stack via the package CLI (Task 8 smoke) with a fresh state dir.
2. In the UI Settings tab: add a custom model provider, set the agent model, add `postgres-prod` + `github` connectors (URLs `http://localhost:8001/mcp`, `http://localhost:8002/mcp`), set the postgres DSN + github token via Services, add the Daytona sandbox key.
3. Click Save & apply agent; verify `GET /api/v1/agents` shows the derived manifest (model, both servers, skill, sandbox enabled).
4. Graceful-degradation check: with NO connectors configured, apply again — the manifest must have empty `mcp_servers` and no skill; the chat must not error.

- [ ] **Step 2: README quickstart**

Add to `README.md`:
```markdown
## Run locally (one command)

```bash
npx @schemaforge/schemaforge
```

Opens the Evidence UI at http://localhost:5173 with TrueForge + both MCP
servers + the registry. Configure models, MCP connectors, services (Postgres
DSN, GitHub token), and the Daytona sandbox in the **Settings** tab, then
Save & apply agent. Unconfigured services are simply omitted — nothing is
hardcoded, nothing crashes.
```
Also add a "Configuration" section describing the five Settings sections and
the graceful-degradation behavior.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/demo-script.md
git commit -m "docs: config-first quickstart + settings documentation"
```

## Execution handoff

1. PR #23 `feat/config-first` — Tasks 1-4 (registry + MCP config). Qodo review -> merge.
2. PR #24 `feat/conditional-instructions` — Tasks 5-6 (instructions + apply_agent wrapper). Qodo -> merge.
3. PR #25 `feat/ui-settings` — Task 7 (Settings tab). Qodo -> merge.
4. PR #26 `feat/npx-package` — Task 8 (npx package). Qodo -> merge.
5. Rework PR #22 `feat/cf-deploy` — Task 9 (config-first deploy). Qodo -> merge.
6. Task 10 (e2e + docs) rides on the final PR of each relevant branch or a small docs PR.