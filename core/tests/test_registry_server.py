import httpx

from schemaforge_core.registry_server import fetch_snapshot, upsert_agent


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
