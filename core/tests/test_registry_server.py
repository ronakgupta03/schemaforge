import httpx

from schemaforge_core.registry_server import (
    _instructions,
    _valid_enabled_servers,
    fetch_snapshot,
    upsert_agent,
)


def _mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_snapshot():
    def handler(request):
        if request.url.path == "/api/v1/settings/mcp-servers":
            return httpx.Response(200, json={"data": [{"name": "github", "url": "http://y/mcp"}]})
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json={"data": [{"name": "cloudflare/deepseek-v4-flash"}]})
        if request.url.path == "/api/v1/capabilities":
            return httpx.Response(200, json={"data": {"sandbox": {"enabled": True}}})
        return httpx.Response(404)

    snap = fetch_snapshot(_mock(handler))
    assert snap.mcp_servers == [{"name": "github", "url": "http://y/mcp"}]
    assert snap.models == ["cloudflare/deepseek-v4-flash"]
    assert snap.sandbox_enabled is True


def test_fetch_snapshot_with_enabled_servers():
    def handler(request):
        if request.url.path == "/api/v1/settings/mcp-servers":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"name": "github", "url": "http://y/mcp"},
                        {"name": "postgres-prod", "url": "http://x/mcp"},
                    ]
                },
            )
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json={"data": [{"name": "cloudflare/deepseek-v4-flash"}]})
        if request.url.path == "/api/v1/capabilities":
            return httpx.Response(200, json={"data": {"sandbox": {"enabled": True}}})
        return httpx.Response(404)

    snap = fetch_snapshot(_mock(handler), enabled_servers=["github"])
    assert snap.mcp_servers == [
        {"name": "github", "url": "http://y/mcp", "enabled": True},
        {"name": "postgres-prod", "url": "http://x/mcp", "enabled": False},
    ]


def test_upsert_agent_existing():
    def handler(request):
        if request.method == "GET" and request.url.path == "/api/v1/agents":
            return httpx.Response(200, json={"data": [{"id": "abc", "name": "schemaforge"}]})
        if request.method == "PUT" and request.url.path == "/api/v1/agents/abc":
            return httpx.Response(200, json={"data": {"id": "abc"}})
        return httpx.Response(500)

    out = upsert_agent(_mock(handler), {"model": {"name": "a/one"}})
    assert out["id"] == "abc"


def test_upsert_agent_creates():
    def handler(request):
        if request.method == "GET" and request.url.path == "/api/v1/agents":
            return httpx.Response(200, json={"data": []})
        if request.method == "POST" and request.url.path == "/api/v1/agents":
            return httpx.Response(200, json={"data": {"id": "new"}})
        return httpx.Response(500)

    out = upsert_agent(_mock(handler), {"model": {"name": "a/one"}})
    assert out["id"] == "new"


def test_valid_enabled_servers():
    assert _valid_enabled_servers([]) is True
    assert _valid_enabled_servers(["github"]) is True
    assert _valid_enabled_servers(["postgres-prod", "mcp_server.1"]) is True
    assert _valid_enabled_servers(42) is False
    assert _valid_enabled_servers("github") is False
    assert _valid_enabled_servers(None) is False
    assert _valid_enabled_servers([""]) is False
    assert _valid_enabled_servers(["123invalid"]) is False
    assert _valid_enabled_servers(["-invalid"]) is False
    assert _valid_enabled_servers(["Upper"]) is False
    assert _valid_enabled_servers([42]) is False
    assert _valid_enabled_servers([None]) is False
    assert _valid_enabled_servers({"github": True}) is False


def test_instructions_fallback_when_file_missing(monkeypatch):
    monkeypatch.setenv("SF_INSTRUCTIONS_PATH", "/nonexistent/path/instructions.md")
    content = _instructions()
    assert (
        content
        == "You are SchemaForge. Follow the schemaforge-migration skill for the migration workflow."
    )


def test_instructions_from_file(monkeypatch, tmp_path):
    p = tmp_path / "instructions.md"
    p.write_text("Custom instructions content")
    monkeypatch.setenv("SF_INSTRUCTIONS_PATH", str(p))
    assert _instructions() == "Custom instructions content"
