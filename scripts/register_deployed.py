"""Post-deploy registration for the Cloudflare-hosted TrueForge (PR #22).

In the config-first model, integrations (MCP servers, model provider,
sandbox) are configured via the Evidence UI Settings tab. This script
performs post-deploy bootstrap:
  1. Skill upsert (git skill from GITHUB_REPO_URL) — via import_skill.py.
  2. Initial agent registration via the registry: POST /api/sf/apply-agent.
"""
from __future__ import annotations

import os
import subprocess
import sys

import httpx

BASE = os.environ.get("TRUEFORGE_URL", "http://localhost:8790")


def apply_agent(client: httpx.Client) -> None:
    r = client.post(
        f"{BASE}/api/sf/apply-agent",
        json={},
    )
    if r.status_code >= 400:
        sys.exit(f"apply-agent failed: {r.status_code} {r.text[:200]}")
    print(f"agent registered via registry: {r.status_code}")


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
    run_script("import_skill.py")
    with httpx.Client(timeout=60) as client:
        apply_agent(client)
    print("deployed registration complete")


if __name__ == "__main__":
    main()
