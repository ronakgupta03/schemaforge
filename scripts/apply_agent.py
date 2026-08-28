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
