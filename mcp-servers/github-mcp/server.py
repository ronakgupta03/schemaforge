"""SchemaForge GitHub MCP server (minimal, in-repo).

Implements the branch/push/PR tools the demo needs. Every action here is
reversible (branches and PRs), so the agent attaches this server with
require_approval_for_tools: [] — the single irreversible approval gate
stays on postgres-prod.execute_ddl.
"""
from __future__ import annotations

import base64
import os

import httpx
from mcp.server.fastmcp import FastMCP

TOKEN = os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"]
API = "https://api.github.com"
_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

mcp = FastMCP("github")


def _client() -> httpx.Client:
    return httpx.Client(headers=_HEADERS, timeout=60)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def get_repo(repo: str) -> dict:
    """Return full_name, default_branch and html_url for `owner/name`."""
    with _client() as c:
        r = c.get(f"{API}/repos/{repo}")
        r.raise_for_status()
        j = r.json()
    return {
        "full_name": j["full_name"],
        "default_branch": j["default_branch"],
        "html_url": j["html_url"],
    }


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def branch_exists(repo: str, branch: str) -> bool:
    """Whether a branch already exists."""
    with _client() as c:
        r = c.get(f"{API}/repos/{repo}/branches/{branch}")
    return r.status_code == 200


@mcp.tool(annotations={"idempotentHint": True, "openWorldHint": False})
def create_branch(repo: str, branch: str, base: str | None = None) -> str:
    """Create `branch` from `base` (defaults to the repo's default branch)."""
    with _client() as c:
        if base is None:
            base = get_repo(repo)["default_branch"]
        br = c.get(f"{API}/repos/{repo}/branches/{base}")
        br.raise_for_status()
        sha = br.json()["commit"]["sha"]
        r = c.post(
            f"{API}/repos/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        if r.status_code == 422:
            return f"branch {branch!r} already exists (no-op)"
        r.raise_for_status()
    return f"created branch {branch!r} from {base!r}"


@mcp.tool(annotations={"idempotentHint": True, "openWorldHint": False})
def write_file(repo: str, path: str, content: str, branch: str, message: str) -> str:
    """Create or update `path` on `branch` with a single commit."""
    with _client() as c:
        cur = c.get(f"{API}/repos/{repo}/contents/{path}?ref={branch}")
        sha = cur.json()["sha"] if cur.status_code == 200 else None
        body = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        r = c.put(f"{API}/repos/{repo}/contents/{path}", json=body)
        r.raise_for_status()
    return f"wrote {path} on {branch}"


@mcp.tool(annotations={"openWorldHint": False})
def open_pull_request(repo: str, title: str, head: str, base: str, body: str = "") -> str:
    """Open a PR from `head` into `base`; returns the PR URL."""
    with _client() as c:
        r = c.post(
            f"{API}/repos/{repo}/pulls",
            json={"title": title, "head": head, "base": base, "body": body},
        )
        r.raise_for_status()
    return r.json()["html_url"]


if __name__ == "__main__":
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = 8002
    mcp.run(transport="streamable-http")