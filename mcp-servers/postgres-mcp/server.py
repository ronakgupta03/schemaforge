"""SchemaForge production-Postgres MCP server.

Exposes read-only introspection tools and exactly one write tool,
`execute_ddl`, annotated destructiveHint so TrueForge's approval gate pauses
before it runs (require_approval_for_tools default matches @destructive).
The only prod write path in the whole system is this tool.
"""
from __future__ import annotations

import os
import re

import psycopg
from mcp.server.fastmcp import FastMCP
from psycopg.rows import dict_row

DSN = os.environ["DATABASE_URL"]  # prod DB, e.g. postgresql://postgres:postgres@localhost:5433/bookstore

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_ALLOWED_DDL = re.compile(
    r"^\s*(CREATE|ALTER|DROP|TRUNCATE|COMMENT|GRANT|REVOKE)\b", re.IGNORECASE
)
_FORBIDDEN = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|COPY|VACUUM|REINDEX)\b", re.IGNORECASE
)

mcp = FastMCP("postgres-prod")


def _conn() -> psycopg.Connection:
    return psycopg.connect(DSN, row_factory=dict_row, autocommit=True)


def _check_ident(name: str) -> None:
    if not _IDENT.match(name):
        raise ValueError(f"invalid identifier: {name!r}")


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
    """Columns (name/type/nullable), primary key, and foreign keys for one table."""
    _check_ident(table)
    with _conn() as conn:
        cols = conn.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
            (table,),
        ).fetchall()
        pks = conn.execute(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = %s::regclass AND i.indisprimary ORDER BY array_position(i.indkey, a.attnum)",
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
            "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name = %s",
            (table,),
        ).fetchall()
    return {"table": table, "columns": cols, "primary_key": [r["attname"] for r in pks], "foreign_keys": fks}


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
    if _FORBIDDEN.search(sql):
        raise ValueError("only DDL is allowed here (no SELECT/INSERT/UPDATE/DELETE/COPY)")
    statements = [s for s in sql.split(";") if s.strip()]
    if not statements:
        raise ValueError("empty DDL batch")
    for stmt in statements:
        if not _ALLOWED_DDL.match(stmt):
            raise ValueError(f"statement not allowed by execute_ddl: {stmt[:80]!r}")
    with _conn() as conn:
        for stmt in statements:
            conn.execute(stmt)
    return f"executed {len(statements)} DDL statement(s) against prod"


if __name__ == "__main__":
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = 8001
    mcp.run(transport="streamable-http")