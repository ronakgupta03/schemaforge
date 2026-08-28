"""SchemaForge production-Postgres MCP server.

Exposes read-only introspection tools and two approval-gated write tools:
`execute_ddl` (pure DDL batches) and `execute_migration` (the full Alembic
migration batch — DDL + data backfill + version stamping — inside ONE
transaction). Both are annotated destructiveHint so TrueForge's approval
gate pauses before they run. The only prod write paths in the whole system
are these tools.
"""
from __future__ import annotations

import json
import os
import re

import psycopg
from mcp.server.fastmcp import FastMCP
from psycopg.rows import dict_row

STATE_DIR = os.environ.get("SF_STATE_DIR", os.path.expanduser("~/.schemaforge"))
_CONFIG_TOKEN = os.environ.get("SF_MCP_CONFIG_TOKEN")
CONFIG_PORT = int(os.environ.get("SF_CONFIG_PORT", "9001"))
_config_httpd = None


def _load_config() -> dict:
    path = os.path.join(STATE_DIR, "postgres-mcp.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    dsn = os.environ.get("DATABASE_URL")
    return {"database_url": dsn}


def _save_config() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "postgres-mcp.json"), "w") as f:
        json.dump(_config, f)


_config: dict = _load_config()

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_ALLOWED_DDL = re.compile(
    r"^\s*(CREATE|ALTER|DROP|TRUNCATE|COMMENT|GRANT|REVOKE)\b", re.IGNORECASE
)
_FORBIDDEN = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|COPY|VACUUM|REINDEX)\b", re.IGNORECASE
)
# Migration batches may additionally carry the data-preserving backfill
# (INSERT INTO <table> ... SELECT ...) and Alembic's own version bookkeeping
# on the alembic_version table. Everything else destructive stays rejected.
_MIGRATION_VERB = re.compile(
    r"^\s*(CREATE|ALTER|DROP|TRUNCATE|COMMENT|GRANT|REVOKE)\b", re.IGNORECASE
)
_INSERT_INTO = re.compile(r"^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_.]*)\b", re.IGNORECASE)
_UPDATE_ALEMBIC = re.compile(r"^\s*UPDATE\s+alembic_version\b", re.IGNORECASE)
_TRANSACTION_FRAME = re.compile(
    r"^\s*(BEGIN|COMMIT|ROLLBACK|START\s+TRANSACTION)\s*$", re.IGNORECASE
)

mcp = FastMCP("postgres-prod")


def _conn(autocommit: bool = True) -> psycopg.Connection:
    dsn = _config.get("database_url")
    if not dsn:
        raise RuntimeError(
            "postgres-prod is not configured: set a DATABASE_URL via the Settings panel or POST /config"
        )
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=autocommit)


def _check_ident(name: str) -> None:
    if not _IDENT.match(name):
        raise ValueError(f"invalid identifier: {name!r}")

def _skip_sql_comment(sql: str, i: int, n: int) -> int:
    """Advance past a -- line comment or /* */ block comment at sql[i:]."""
    if sql.startswith("--", i):
        j = sql.find("\n", i)
        return n if j == -1 else j  # keep the newline (statement separator)
    j = sql.find("*/", i + 2)
    return n if j == -1 else j + 2


def _split_statements(sql: str) -> list[str]:
    """Split on ';' outside quoted literals and comments.

    Honors single-quoted strings ('...', with '' as an escaped quote),
    PostgreSQL dollar-quoted bodies ($tag$...$tag$ and $$...$$), -- line
    comments, and /* */ block comments, so a semicolon inside any of those
    never fragments the batch.
    """
    parts: list[str] = []
    start = 0
    i, n = 0, len(sql)
    in_str = False
    dollar_tag: str | None = None
    while i < n:
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, i):
                tag = dollar_tag
                dollar_tag = None
                i += len(tag)
            else:
                i += 1
            continue
        ch = sql[i]
        if in_str:
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    i += 2  # escaped quote inside the literal
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            i += 1
        elif ch == "$":
            m = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", sql[i:])
            if m:
                dollar_tag = m.group(0)
                i += len(dollar_tag)
            else:
                i += 1
        elif sql.startswith("--", i) or sql.startswith("/*", i):
            i = _skip_sql_comment(sql, i, n)
        elif ch == ";":
            parts.append(sql[start:i].strip())
            i += 1
            start = i
        else:
            i += 1
    parts.append(sql[start:].strip())
    return [p for p in parts if p]


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def list_tables() -> list[str]:
    """All tables in the public schema, sorted."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()
    return [r["table_name"] for r in rows]


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def table_schema(table: str) -> dict:
    """Columns (name/type/nullable/default), indexes, and foreign keys for one table."""
    _check_ident(table)
    with _conn() as conn:
        cols = conn.execute(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
            (table,),
        ).fetchall()
        indexes = conn.execute(
            "SELECT i.relname AS name, ix.indisunique AS unique_, "
            "array_agg(a.attname ORDER BY array_position(ix.indkey, a.attnum)) AS columns "
            "FROM pg_index ix JOIN pg_class i ON i.oid = ix.indexrelid "
            "JOIN pg_class t ON t.oid = ix.indrelid "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey) "
            "WHERE t.relname = %s AND t.relnamespace = 'public'::regnamespace "
            "GROUP BY i.relname, ix.indisunique ORDER BY i.relname",
            (table,),
        ).fetchall()
        fks = conn.execute(
            "SELECT tc.constraint_name, kcu.column_name, ccu.table_name AS ref_table, "
            "ccu.column_name AS ref_column "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema "
            "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public' "
            "AND tc.table_name = %s",
            (table,),
        ).fetchall()
    return {
        "table": table,
        "columns": [
            {"name": c["column_name"], "data_type": c["data_type"],
             "nullable": c["is_nullable"] == "YES", "default": c["column_default"]}
            for c in cols
        ],
        "indexes": [
            {"name": i["name"], "columns": i["columns"], "unique": i["unique_"]}
            for i in indexes
        ],
        "foreign_keys": [
            {"name": f["constraint_name"], "column": f["column_name"],
             "ref_table": f["ref_table"], "ref_column": f["ref_column"]}
            for f in fks
        ],
    }


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def row_count(table: str) -> int:
    """Exact row count for one table (O(n) scan — fine at demo scale)."""
    _check_ident(table)
    with _conn() as conn:
        return conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()["count"]


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def explain(sql: str) -> str:
    """EXPLAIN (no ANALYZE) for a SELECT — never executes writes or heavy scans on prod."""
    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        raise ValueError("explain() only accepts SELECT statements")
    with _conn() as conn:
        rows = conn.execute(f"EXPLAIN {sql}").fetchall()
    return "\n".join(r["QUERY PLAN"] for r in rows)


@mcp.tool(
    annotations={"destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    description=(
        "Execute DDL (CREATE/ALTER/DROP/...) against the production database. "
        "Irreversible — the harness pauses this call for human approval."
    ),
)
def execute_ddl(sql: str) -> str:
    """Run a DDL statement or semicolon-separated DDL batch against prod."""
    clean = _strip_sql_comments(sql)
    if _FORBIDDEN.search(clean):
        raise ValueError("only DDL is allowed here (no SELECT/INSERT/UPDATE/DELETE/COPY)")
    statements = _split_statements(clean)
    if not statements:
        raise ValueError("empty DDL batch")
    for stmt in statements:
        if not _ALLOWED_DDL.match(stmt):
            raise ValueError(f"statement not allowed by execute_ddl: {stmt[:80]!r}")
    with _conn() as conn:
        for stmt in statements:
            conn.execute(stmt)
    return f"executed {len(statements)} DDL statement(s) against prod"


def _strip_sql_comments(statement: str) -> str:
    """Remove -- line and /* */ block comments (never inside quoted literals)."""
    out: list[str] = []
    i, n = 0, len(statement)
    in_str = False
    while i < n:
        ch = statement[i]
        if in_str:
            out.append(ch)
            if ch == "'":
                if i + 1 < n and statement[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            out.append(ch)
            i += 1
        elif statement.startswith("--", i) or statement.startswith("/*", i):
            i = _skip_sql_comment(statement, i, n)
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _validate_migration_statement(statement: str) -> None:
    stmt = _strip_sql_comments(statement)
    if not stmt:
        raise ValueError("empty statement in migration batch")
    if _MIGRATION_VERB.match(stmt):
        return
    m = _INSERT_INTO.match(stmt)
    if m:
        target = m.group(1).lower()
        if target == "alembic_version":
            return  # Alembic version bookkeeping
        if re.search(r"\bSELECT\b", stmt, re.IGNORECASE):
            return  # data backfill — target existence is checked at apply time
    if _UPDATE_ALEMBIC.match(stmt):
        return  # Alembic version bookkeeping only
    raise ValueError(f"statement not allowed by execute_migration: {stmt[:80]!r}")


def _existing_tables(conn: psycopg.Connection) -> set[str]:
    """Tables that exist in prod BEFORE this migration runs."""
    return {
        r["table_name"]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
    }


@mcp.tool(
    annotations={"destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    description=(
        "Apply a full Alembic migration batch (DDL + data backfill + version "
        "stamping) against the production database inside ONE transaction — a "
        "failure rolls back every earlier statement. Irreversible — the "
        "harness pauses this call for human approval."
    ),
)
def execute_migration(sql: str) -> str:
    """Run an `alembic upgrade 0001:head --sql` batch on prod, atomically."""
    statements = _split_statements(sql)
    if not statements:
        raise ValueError("empty migration batch")
    # Alembic's offline output frames the batch with BEGIN/COMMIT; the tool
    # runs its own single transaction, so the framing is dropped.
    statements = [
        s for s in statements if not _TRANSACTION_FRAME.match(_strip_sql_comments(s))
    ]
    if not statements:
        raise ValueError("migration batch contains only transaction framing")
    for stmt in statements:
        _validate_migration_statement(stmt)
    with _conn(autocommit=False) as conn:
        pre = _existing_tables(conn)
        try:
            for i, stmt in enumerate(statements, 1):
                clean = _strip_sql_comments(stmt)
                m = _INSERT_INTO.match(clean)
                if m:
                    target = m.group(1).lower()
                    if target != "alembic_version" and target in pre:
                        raise ValueError(
                            f"backfill target {target!r} already exists — INSERT..SELECT "
                            "may only populate tables created by this migration"
                        )
                conn.execute(clean)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise RuntimeError(
                f"migration aborted and rolled back at statement {i}/{len(statements)}: {exc}"
            ) from exc
    return f"applied {len(statements)} migration statement(s) in one transaction"


from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ConfigHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
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
            return self._send(200, {"data": {"configured": bool(_config.get("database_url"))}})
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
        dsn = body.get("database_url")
        if not dsn or not dsn.startswith(("postgresql://", "postgres://")):
            return self._send(400, {"error": "database_url must be a postgresql:// DSN"})
        _config["database_url"] = dsn
        _save_config()
        return self._send(202, {"data": {"ok": True, "configured": True}})


def run_config_server(host: str = "127.0.0.1") -> None:
    global _config_httpd
    _config_httpd = ThreadingHTTPServer((host, CONFIG_PORT), ConfigHandler)
    print(f"postgres-mcp config endpoint on {host}:{CONFIG_PORT}")
    _config_httpd.serve_forever()


if __name__ == "__main__":
    mcp.settings.host = "0.0.0.0"
    # Cloudflare containers: outbound interception is HTTP(S) ports 80/443
    # only, so the deployed container listens on 80 (PORT env from the
    # container class envVars). Local dev keeps the default 8001.
    mcp.settings.port = int(os.environ.get("PORT", "8001"))
    mcp.run(transport="streamable-http")