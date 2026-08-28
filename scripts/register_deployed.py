"""Post-deploy registration for the Cloudflare-hosted TrueForge (PR #22).

Creates every settings manifest the deployed agent needs, against the
deployed TrueForge (TRUEFORGE_URL). The metadata DB on Neon is persistent,
but the settings API entries are created via the API and do not survive a
container restart, so re-run this after any fresh container boot.

Steps:
  1. MCP server settings: postgres-prod + github at their container-internal
     URLs (http://postgres-mcp.internal/mcp etc.) — reachable only from the
     TrueForge container via outboundByHost, never from the internet.
  2. Cloudflare model provider (custom, base_url Workers AI, DeepSeek models).
  3. Skill upsert (git skill from GITHUB_REPO_URL) — same as import_skill.py.
  4. Agent upsert (apply_agent.py manifest) with sandbox + approval gate.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import httpx

BASE = os.environ.get("TRUEFORGE_URL", "http://localhost:8790")


def upsert_mcp_servers(client: httpx.Client) -> None:
    servers = [
        {
            "type": "remote",
            "name": "postgres-prod",
            "url": "http://postgres-mcp.internal/mcp",
            "description": "Production Postgres: read-only introspection + approval-gated migration apply (Cloudflare container).",
        },
        {
            "type": "remote",
            "name": "github",
            "url": "http://github-mcp.internal/mcp",
            "description": "GitHub: branch/PR tools (Cloudflare container).",
        },
    ]
    for manifest in servers:
        r = client.put(
            f"{BASE}/api/v1/settings/mcp-servers",
            json={"manifest": manifest},
        )
        if r.status_code >= 400:
            sys.exit(f"mcp-server upsert failed for {manifest['name']}: {r.status_code} {r.text[:200]}")
        print(f"mcp-server {manifest['name']} registered")


def upsert_model_provider(client: httpx.Client) -> None:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    api_token = os.environ.get("CLOUDFLARE_AUTH_TOKEN")
    if not account_id or not api_token:
        sys.exit("CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_AUTH_TOKEN required")
    manifest = {
        "type": "custom",
        "name": "cloudflare",
        "base_url": f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "auth": {"api_key": api_token},
        "models": [
            {"model_id": "@cf/deepseek-ai/deepseek-v4-flash-0731", "name": "deepseek-v4-flash", "properties": {}},
            {"model_id": "@cf/deepseek-ai/deepseek-v4-pro-0813", "name": "deepseek-v4-pro", "properties": {}},
        ],
    }
    r = client.put(
        f"{BASE}/api/v1/settings/model-providers",
        json={"manifest": manifest},
    )
    if r.status_code >= 400:
        sys.exit(f"model-provider upsert failed: {r.status_code} {r.text[:200]}")
    print("model-provider cloudflare registered")


def run_script(name: str) -> None:
    env = dict(os.environ)
    env["TRUEFORGE_URL"] = BASE
    p = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(__file__), name)],
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    if p.returncode != 0:
        sys.exit(f"{name} failed with rc={p.returncode}")


def main() -> None:
    with httpx.Client(timeout=60) as client:
        upsert_mcp_servers(client)
        upsert_model_provider(client)
    run_script("import_skill.py")
    run_script("apply_agent.py")
    print("deployed registration complete")


if __name__ == "__main__":
    main()