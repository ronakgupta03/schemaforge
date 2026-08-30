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
ITERATION_LIMIT = 100
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
    enabled_servers: list[str] | None = None,
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
        if s.get("enabled", True) and (enabled_servers is None or s["name"] in enabled_servers)
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
