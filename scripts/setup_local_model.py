"""Register the local llama.cpp server as a TrueForge custom model provider.

Auto-discovers models via GET {LLM_BASE_URL}/models so swapping GGUFs later
needs no code change. PUT /api/v1/settings/model-providers is create-or-
replace keyed by provider name; llama.cpp ignores auth, so a dummy api_key
is sent (the schema requires one).
"""
from __future__ import annotations

import json
import os
import re
import sys

import httpx

BASE = os.environ.get("TRUEFORGE_URL", "http://localhost:8790")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1")
PROVIDER = "local"


def to_resource_name(model_id: str) -> str:
    """Map an upstream model id onto the ResourceName pattern."""
    name = re.sub(r"[^a-z0-9._-]", "-", model_id.lower().replace("/", "-"))
    name = name.strip("-._") or "model"
    if not name[0].isalpha():
        name = "m-" + name
    return name[:64]


def main() -> None:
    with httpx.Client(timeout=30) as client:
        r = client.get(f"{LLM_BASE_URL}/models")
        if r.status_code >= 400:
            sys.exit(f"local model server unreachable: {r.status_code} {r.text[:200]}")
        ids = [m["id"] for m in r.json().get("data", [])]
        if not ids:
            sys.exit(f"no models served at {LLM_BASE_URL}/models")
        models = [
            {"model_id": mid, "name": to_resource_name(mid), "properties": {}}
            for mid in ids
        ]
        manifest = {
            "type": "custom",
            "name": PROVIDER,
            "base_url": LLM_BASE_URL,
            "auth": {"api_key": "llamacpp"},  # ignored by the server
            "models": models,
        }
        resp = client.put(
            f"{BASE}/api/v1/settings/model-providers", json={"manifest": manifest}
        )
    if resp.status_code >= 400:
        sys.exit(f"model-provider update failed: {resp.status_code} {resp.text}")
    print(json.dumps(resp.json(), indent=2))
    print("\nFQNs now available:")
    for m in models:
        print(f"  {PROVIDER}/{m['name']}")


if __name__ == "__main__":
    main()