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
    assert m["config"]["iteration_limit"] == 100


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


def test_enabled_servers_list_filters():
    snap = SettingsSnapshot(
        mcp_servers=[
            {"name": "postgres-prod", "url": "http://x/mcp", "description": ""},
            {"name": "github", "url": "http://y/mcp", "description": ""},
        ],
        models=["cloudflare/deepseek-v4-flash"],
        sandbox_enabled=True,
    )
    m = build_manifest(snap, INSTRUCTIONS, model_fqn=None, overrides={}, enabled_servers=["postgres-prod"])
    names = [s["name"] for s in m["mcp_servers"]]
    assert names == ["postgres-prod"]


def test_explicit_enabled_false_overrides_list():
    snap = SettingsSnapshot(
        mcp_servers=[
            {"name": "postgres-prod", "url": "http://x/mcp", "description": "", "enabled": False},
            {"name": "github", "url": "http://y/mcp", "description": ""},
        ],
        models=["cloudflare/deepseek-v4-flash"],
        sandbox_enabled=True,
    )
    m = build_manifest(snap, INSTRUCTIONS, model_fqn=None, overrides={}, enabled_servers=["postgres-prod", "github"])
    names = [s["name"] for s in m["mcp_servers"]]
    assert names == ["github"]
