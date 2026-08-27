"""Create/update the 'schemaforge' agent in the running TrueForge instance."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

BASE = os.environ.get("TRUEFORGE_URL", "http://localhost:8790")
HERE = Path(__file__).resolve().parent


def main() -> None:
    instructions = (HERE.parent / "agent" / "instructions.md").read_text()
    manifest = {
        "model": {"name": os.environ.get("SCHEMAFORGE_MODEL", "local/qwen3.8-27b")},
        "instructions": instructions,
        # Agents reference MCP servers by NAME; url/auth live in the settings
        # manifests (admin-only), never in the agent spec.
        "mcp_servers": [
            {
                "name": "postgres-prod",
                "enable_tools": ["@all"],
                "preload": True,
                "require_approval_for_tools": ["@write", "@destructive"],
            },
            {
                "name": "github",
                "enable_tools": ["@all"],
                "preload": False,
                "require_approval_for_tools": [],
            },
        ],
        "skills": [{"name": "schemaforge-migration"}],
        "config": {
            "sandbox": {"enabled": True},
            "dynamic_sub_agents": {"enabled": True},
            "generative_ui": {"enabled": True},
            "ask_user_questions": {"enabled": True},
            "iteration_limit": 60,
        },
    }
    with httpx.Client(base_url=BASE, timeout=30) as client:
        existing = None
        for a in client.get("/api/v1/agents").json().get("data", []):
            if a.get("name") == "schemaforge":
                existing = a
                break
        if existing:
            resp = client.put(f"/api/v1/agents/{existing['id']}", json={"manifest": manifest})
        else:
            resp = client.post("/api/v1/agents", json={"name": "schemaforge", "manifest": manifest})
    if resp.status_code >= 400:
        raise SystemExit(f"agent upsert failed: {resp.status_code} {resp.text}")
    print(json.dumps(resp.json(), indent=2))


if __name__ == "__main__":
    main()