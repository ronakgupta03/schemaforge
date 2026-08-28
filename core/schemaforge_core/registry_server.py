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


def fetch_snapshot(client: httpx.Client, base_url: str = TRUEFORGE_URL) -> SettingsSnapshot:
    servers = client.get(f"{base_url}/api/v1/settings/mcp-servers").json().get("data", [])
    models = client.get(f"{base_url}/api/v1/models").json().get("data", [])
    caps = client.get(f"{base_url}/api/v1/capabilities").json().get("data", {})
    return SettingsSnapshot(
        mcp_servers=[
            {k: s[k] for k in ("name", "url", "description") if k in s}
            for s in servers
        ],
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
