"""Import the schemaforge-migration skill from this repo into TrueForge."""
from __future__ import annotations

import json
import os
import sys

import httpx

BASE = os.environ.get("TRUEFORGE_URL", "http://localhost:8790")
REPO = os.environ["GITHUB_REPO_URL"]  # e.g. https://github.com/<you>/schemaforge


def main() -> None:
    manifest = {
        "name": "schemaforge-migration",
        "type": "git",
        "url": REPO,
        "ref": "main",
        "path": "skills/schemaforge-migration",
        "description": "SchemaForge migration workflow",
    }
    with httpx.Client(base_url=BASE, timeout=60) as client:
        resp = client.post("/api/v1/settings/skills", json={"manifest": manifest})
        if resp.status_code == 409:
            resp = client.put("/api/v1/settings/skills", json={"manifest": manifest})
        if resp.status_code >= 400:
            sys.exit(f"skill import failed: {resp.status_code} {resp.text}")
    print(json.dumps(resp.json(), indent=2))


if __name__ == "__main__":
    main()