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
_AGENT_INSTRUCTIONS_PATH = os.environ.get("SF_INSTRUCTIONS_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "agent",
    "instructions.md",
)

def fetch_snapshot(
    client: httpx.Client,
    base_url: str = TRUEFORGE_URL,
    enabled_servers: list[str] | None = None,
) -> SettingsSnapshot:
    servers = client.get(f"{base_url}/api/v1/settings/mcp-servers").json().get("data", [])
    models = client.get(f"{base_url}/api/v1/models").json().get("data", [])
    caps = client.get(f"{base_url}/api/v1/capabilities").json().get("data", {})
    mcp_servers = []
    for s in servers:
        d = {k: s[k] for k in ("name", "url", "description") if k in s}
        if enabled_servers is not None:
            d["enabled"] = s.get("name") in enabled_servers
        mcp_servers.append(d)
    return SettingsSnapshot(
        mcp_servers=mcp_servers,
        models=[m.get("name") for m in models],
        sandbox_enabled=bool((caps.get("sandbox") or {}).get("enabled")),
    )


def upsert_agent(client: httpx.Client, manifest: dict[str, Any], base_url: str = TRUEFORGE_URL) -> dict[str, Any]:
    existing = None
    for a in client.get(f"{base_url}/api/v1/agents").json().get("data", []):
        if a.get("name") == AGENT_NAME:
            existing = a
            break
    if existing:
        r = client.put(f"{base_url}/api/v1/agents/{existing['id']}", json={"manifest": manifest})
    else:
        r = client.post(f"{base_url}/api/v1/agents", json={"name": AGENT_NAME, "manifest": manifest})
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
            state = load_agent_state()
            with httpx.Client(timeout=30) as c:
                snap = fetch_snapshot(c, enabled_servers=state.get("enabled_servers"))
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
                enabled_servers = body.get("enabled_servers")
                with httpx.Client(timeout=60) as c:
                    state = load_agent_state()
                    if enabled_servers is None:
                        enabled_servers = state.get("enabled_servers")
                    snap = fetch_snapshot(c, enabled_servers=enabled_servers)
                    model = body.get("model") or state.get("model")
                    manifest = build_manifest(
                        snap,
                        _instructions(),
                        model,
                        body.get("overrides", {}),
                        enabled_servers=enabled_servers,
                    )
                    upsert_agent(c, manifest)
                    new_state = dict(state)
                    if model:
                        new_state["model"] = model
                    if enabled_servers is not None:
                        new_state["enabled_servers"] = enabled_servers
                    save_agent_state(new_state)
                return self._send(
                    200,
                    {"data": {"manifest": manifest, "omitted": [s["name"] for s in snap.mcp_servers if not s.get("enabled", True)]}},
                )
            except Exception as exc:
                return self._send(422, {"error": str(exc)})
        if self.path == "/config":
            state = load_agent_state()
            model = body.get("model")
            enabled_servers = body.get("enabled_servers")
            if not model and enabled_servers is None:
                return self._send(400, {"error": "model or enabled_servers required"})
            if model:
                state["model"] = model
            if enabled_servers is not None:
                state["enabled_servers"] = enabled_servers
            save_agent_state(state)
            return self._send(200, {"data": state})
        self._send(404, {"error": "not found"})


def run_server(host: str = "127.0.0.1", port: int | None = None) -> None:
    port = port or DEFAULT_PORT
    print(f"sf-registry on {host}:{port} -> TrueForge {TRUEFORGE_URL}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main() -> None:
    run_server(host=os.environ.get("SF_REGISTRY_HOST", "127.0.0.1"))


if __name__ == "__main__":
    main()
