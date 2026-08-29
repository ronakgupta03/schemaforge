"""SchemaForge GitHub MCP server (minimal, in-repo).

Implements the branch/push/PR tools the demo needs. Every action here is
reversible (branches and PRs), so the agent attaches this server with
require_approval_for_tools: [] — the single irreversible approval gate
stays on postgres-prod.execute_ddl.
"""
from __future__ import annotations

import base64
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from mcp.server.fastmcp import FastMCP

API = "https://api.github.com"
# Cap archive downloads so a huge repo cannot exhaust server memory (the
# tarball is buffered then base64-encoded in-process; see get_repo_archive).
_MAX_ARCHIVE_BYTES = int(os.environ.get("SF_MAX_ARCHIVE_BYTES", str(100 * 1024 * 1024)))  # 100 MiB default
STATE_DIR = os.environ.get("SF_STATE_DIR", os.path.expanduser("~/.schemaforge"))
_CONFIG_TOKEN = os.environ.get("SF_MCP_CONFIG_TOKEN")
CONFIG_PORT = int(os.environ.get("SF_CONFIG_PORT", "9002"))
_config_httpd = None


def _load_config() -> dict:
    path = os.path.join(STATE_DIR, "github-mcp.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"token": os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN"), "default_repo": None}


def _save_config() -> None:
    os.makedirs(STATE_DIR, exist_ok=True, mode=0o700)
    path = os.path.join(STATE_DIR, "github-mcp.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(_config, f)


_config: dict = _load_config()


def _normalize_repo(repo) -> str:
    """Normalize a repo reference to `owner/name`.

    Accepts `owner/name` or a full GitHub URL (`https://github.com/owner/name`,
    with optional `www.`, trailing `/` or `.git`). Returns "" when the result
    is not exactly two path components, so callers can raise a clear error.
    """
    if not isinstance(repo, str) or not repo.strip():
        return ""
    s = repo.strip()
    if "://" in s:
        s = s.split("://", 1)[1]
    if s.startswith("www."):
        s = s[len("www."):]
    if s.startswith("github.com/"):
        s = s[len("github.com/"):]
    s = s.rstrip("/")
    if s.endswith(".git"):
        s = s[:-4]
    parts = s.split("/")
    if len(parts) == 2 and all(parts):
        return f"{parts[0]}/{parts[1]}"
    return ""


def _resolve_repo(repo: str) -> str:
    if repo:
        norm = _normalize_repo(repo)
        if not norm:
            raise ValueError(
                f"invalid repo {repo!r}: expected `owner/name` or a GitHub URL "
                f"like https://github.com/owner/name"
            )
        return norm
    return _normalize_repo(_config.get("default_repo") or "")


mcp = FastMCP("github")


def _client() -> httpx.Client:
    token = _config.get("token")
    if not token:
        raise RuntimeError(
            "github is not configured: set a token in Settings -> SchemaForge (GitHub connector), or POST /config on :9002"
        )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    return httpx.Client(headers=headers, timeout=60)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def get_repo(repo: str = "") -> dict:
    """Return full_name, default_branch and html_url for `owner/name`."""
    repo = _resolve_repo(repo)
    if not repo:
        raise ValueError("no repo: pass repo or set default_repo via POST /config")
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
def get_repo_archive(repo: str = "", ref: str = "") -> dict:
    """Download the repo source tree as a gzipped tarball, base64-encoded.

    Uses the configured GitHub token, so PRIVATE repos are accessible without
    exposing credentials to the sandbox (the sandbox has no git creds and
    cannot `git clone` a private repo). Returns {repo, ref, sha, format,
    archive_base64}. Decode + extract, e.g.:
        base64 -d <b64> | tar xzf - --strip-components=1 -C /workspace/app
    For large repos, fetch via the sandbox `mcp-client` CLI and pipe straight
    to a file so the blob never enters the model context.

    `sha` is the immutable commit the archive was built from: the ref is
    resolved to a SHA first, then the tarball is fetched BY that SHA so a
    branch update between the two requests cannot shift the content
    (resolution failures raise instead of silently substituting the ref).
    Archives larger than _MAX_ARCHIVE_BYTES are rejected to bound memory.
    """
    repo = _resolve_repo(repo)
    if not repo:
        raise ValueError("no repo: pass repo or set default_repo via POST /config")
    with _client() as c:
        if not ref:
            r = c.get(f"{API}/repos/{repo}")
            r.raise_for_status()
            ref = r.json()["default_branch"]
        # Resolve ref -> immutable commit SHA; fail clearly (never substitute ref).
        rc = c.get(f"{API}/repos/{repo}/commits/{ref}")
        rc.raise_for_status()
        sha = rc.json()["sha"]
        # Fetch the tarball by the immutable SHA, not the mutable branch name.
        a = c.get(f"{API}/repos/{repo}/tarball/{sha}", follow_redirects=True, timeout=300)
        a.raise_for_status()
        data = a.content
    if len(data) > _MAX_ARCHIVE_BYTES:
        raise ValueError(
            f"archive too large: {len(data)} bytes exceeds the "
            f"{_MAX_ARCHIVE_BYTES} byte cap (raise it with SF_MAX_ARCHIVE_BYTES "
            f"or reduce the repo size; the sandbox cannot clone private repos)"
        )
    return {
        "repo": repo,
        "ref": ref,
        "sha": sha,
        "format": "tar.gz",
        "archive_base64": base64.b64encode(data).decode("ascii"),
    }

@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def branch_exists(repo: str = "", branch: str = "") -> bool:
    """Whether a branch already exists."""
    repo = _resolve_repo(repo)
    if not repo:
        raise ValueError("no repo: pass repo or set default_repo via POST /config")
    with _client() as c:
        r = c.get(f"{API}/repos/{repo}/branches/{branch}")
    return r.status_code == 200


@mcp.tool(annotations={"idempotentHint": True, "openWorldHint": False})
def create_branch(repo: str = "", branch: str = "", base: str | None = None) -> str:
    """Create `branch` from `base` (defaults to the repo's default branch)."""
    repo = _resolve_repo(repo)
    if not repo:
        raise ValueError("no repo: pass repo or set default_repo via POST /config")
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
def write_file(repo: str = "", path: str = "", content: str = "", branch: str = "", message: str = "") -> str:
    """Create or update `path` on `branch` with a single commit."""
    repo = _resolve_repo(repo)
    if not repo:
        raise ValueError("no repo: pass repo or set default_repo via POST /config")
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
def open_pull_request(repo: str = "", title: str = "", head: str = "", base: str = "", body: str = "") -> str:
    """Open a PR from `head` into `base`; returns the PR URL."""
    repo = _resolve_repo(repo)
    if not repo:
        raise ValueError("no repo: pass repo or set default_repo via POST /config")
    with _client() as c:
        r = c.post(
            f"{API}/repos/{repo}/pulls",
            json={"title": title, "head": head, "base": base, "body": body},
        )
        r.raise_for_status()
    return r.json()["html_url"]

@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def get_pull_request(repo: str = "", number: int = 0) -> dict:
    """Return PR state + review comments (e.g. Qodo findings) for PR `number`."""
    repo = _resolve_repo(repo)
    if not repo:
        raise ValueError("no repo: pass repo or set default_repo via POST /config")
    if not number:
        raise ValueError("number is required")
    with _client() as c:
        pr = c.get(f"{API}/repos/{repo}/pulls/{number}")
        pr.raise_for_status()
        prj = pr.json()
        comments = []
        ic = c.get(f"{API}/repos/{repo}/issues/{number}/comments")
        if ic.status_code == 200:
            for cm in ic.json():
                comments.append({"user": cm["user"]["login"], "body": cm["body"], "url": cm["html_url"]})
        reviews = []
        rv = c.get(f"{API}/repos/{repo}/pulls/{number}/reviews")
        if rv.status_code == 200:
            for r in rv.json():
                reviews.append({"user": r["user"]["login"], "state": r["state"], "body": r["body"]})
    return {
        "number": prj["number"],
        "title": prj["title"],
        "state": prj["state"],
        "html_url": prj["html_url"],
        "mergeable": prj.get("mergeable"),
        "comments": comments,
        "reviews": reviews,
    }


class ConfigHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not _CONFIG_TOKEN:
            self._send(503, {"error": "config disabled: SF_MCP_CONFIG_TOKEN unset"})
            return False
        if self.headers.get("Authorization") != f"Bearer {_CONFIG_TOKEN}":
            self._send(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:
        if self.path == "/config":
            if not self._authorized():
                return
            return self._send(200, {"data": {"configured": bool(_config.get("token"))}})
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/config":
            return self._send(404, {"error": "not found"})
        if not self._authorized():
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "invalid JSON"})
        token = body.get("token")
        default_repo = body.get("default_repo")
        if not token and not default_repo:
            return self._send(400, {"error": "at least one of 'token' or 'default_repo' is required"})
        if token:
            if not isinstance(token, str) or not token.startswith(("ghp_", "github_pat_", "gho_", "ghu_")):
                return self._send(400, {"error": "token must start with ghp_, github_pat_, gho_, or ghu_"})
            _config["token"] = token
        if default_repo:
            if not isinstance(default_repo, str) or not _normalize_repo(default_repo):
                return self._send(400, {"error": "default_repo must be `owner/name` or a GitHub URL like https://github.com/owner/name"})
            _config["default_repo"] = default_repo
        _save_config()
        return self._send(202, {"data": {"ok": True, "configured": bool(_config.get("token"))}})


    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

def run_config_server(host: str = "127.0.0.1") -> None:
    global _config_httpd
    _config_httpd = ThreadingHTTPServer((host, CONFIG_PORT), ConfigHandler)
    print(f"github-mcp config endpoint on {host}:{CONFIG_PORT}")
    _config_httpd.serve_forever()


if __name__ == "__main__":
    import threading

    threading.Thread(target=run_config_server, daemon=True).start()
    mcp.settings.host = "0.0.0.0"
    # Cloudflare containers: outbound interception is HTTP(S) ports 80/443
    # only, so the deployed container listens on 80 (PORT env from the
    # container class envVars). Local dev keeps the default 8002.
    mcp.settings.port = int(os.environ.get("PORT", "8002"))
    mcp.run(transport="streamable-http")
