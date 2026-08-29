"""Deterministic code facts from a TypeScript / Drizzle ORM source tree.

Generic over any Drizzle ORM app (pgTable/sqliteTable/mysqlTable) and any
Hono/Express-style router. Pure-Python static extraction — no tree-sitter, no
Node runtime. Column *types* are not parsed: they come from the live DB
snapshot. Two passes mirror the Python extractor (models first -> name map,
then endpoints/accesses/raw_sql/calls).
"""
from __future__ import annotations

import re
from pathlib import Path

from .models import (
    AttrAccess,
    CodeFacts,
    EndpointFact,
    FunctionCall,
    ModelFact,
    RawSqlRef,
)

_BUILDERS = ("pgTable", "sqliteTable", "mysqlTable")
_SKIP_DIRS = {"node_modules", "dist", "build", ".git", ".next", "coverage"}

# export const NAME = BUILDER('table', {  ... (capture up to the column-object '{')
_RE_MODEL = re.compile(
    r"export\s+const\s+(\w+)\s*=\s*(\w+Table)\s*\(\s*"
    r"(['\"])(?P<table>[^'\"]+)\3\s*,\s*\{"
)
# column key: builder('sqlname'   OR  key: builder() (no name)
_RE_COL_NAMED = re.compile(r"(\w+)\s*:\s*\w+\s*\(\s*(['\"])(?P<sql>[^'\"]+)\2")
_RE_COL_KEYS = re.compile(r"(\w+)\s*:\s*")
# ROUTER.METHOD('/path', handler)  — any router var (Hono/Express)
_RE_ROUTE = re.compile(
    r"\b(\w+)\.(?P<method>get|post|put|patch|delete)\s*\(\s*"
    r"(['\"])(?P<path>[^'\"]+)\3\s*,"
)
_RE_SCHEMA_ACCESS = re.compile(r"schema\.(\w+)\.(\w+)")
_RE_FROM_SCHEMA = re.compile(r"\.from\(\s*schema\.(\w+)\s*\)")
# .insert/update/delete(schema.X) — table-level writes
_RE_TABLE_WRITE = re.compile(r"\.(?:insert|update|delete)\(\s*schema\.(\w+)\s*\)")
_RE_DB_QUERY = re.compile(r"\bdb\.query\.(\w+)\b")
_RE_SQL_TICK = re.compile(r"sql`([^`]*)`")
# named function call: foo(...) where foo is a declared function name
_RE_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")


def _iter_ts(root: Path):
    for p in sorted(root.rglob("*.ts")):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        yield p


def _balance(src: str, open_idx: int, open_ch: str = "{", close_ch: str = "}") -> int:
    """Return index of the matching close char for the open at open_idx, or -1."""
    depth = 0
    i = open_idx
    in_s = in_d = in_t = False
    while i < len(src):
        ch = src[i]
        if in_s:
            in_s = ch != "'"
        elif in_d:
            in_d = ch != '"'
        elif in_t:
            in_t = ch != "`"
        else:
            if ch == "'":
                in_s = True
            elif ch == '"':
                in_d = True
            elif ch == "`":
                in_t = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _line_of(src: str, idx: int) -> int:
    return src.count("\n", 0, idx) + 1


def _column_sql_names(obj_body: str) -> list[str]:
    """SQL column names: first string arg of each builder, fallback the JS key."""
    named = {m.group(1): m.group("sql") for m in _RE_COL_NAMED.finditer(obj_body)}
    cols: list[str] = []
    seen: set[str] = set()
    for m in _RE_COL_KEYS.finditer(obj_body):
        key = m.group(1)
        sql = named.get(key, key)  # fallback to JS key when no name arg
        if sql not in seen:
            seen.add(sql)
            cols.append(sql)
    return cols


def _collect_models(src: str, rel: str, facts: CodeFacts) -> dict[str, str]:
    """Pass 1: Drizzle table models. Returns jsname -> sql table name."""
    name_map: dict[str, str] = {}
    for m in _RE_MODEL.finditer(src):
        builder = m.group(2)
        if builder not in _BUILDERS:
            continue
        name, table = m.group(1), m.group("table")
        obj_open = m.end() - 1  # the '{'
        close = _balance(src, obj_open)
        body = src[obj_open + 1:close] if close > 0 else src[obj_open + 1:]
        facts.models.append(ModelFact(
            name=name, table=table, columns=_column_sql_names(body),
            file=rel, line=_line_of(src, m.start()),
        ))
        name_map[name] = table
    return name_map


def _resolve_tables(handler_body: str, name_map: dict[str, str]) -> list[str]:
    """SQL table names touched: .from(schema.X) / .insert/update/delete(schema.X)
    / db.query.X / any schema.X inside sql``."""
    tables: list[str] = []
    seen: set[str] = set()

    def _add(js: str) -> None:
        t = name_map.get(js, js)
        if t not in seen:
            seen.add(t)
            tables.append(t)

    for m in _RE_FROM_SCHEMA.finditer(handler_body):
        _add(m.group(1))
    for m in _RE_TABLE_WRITE.finditer(handler_body):
        _add(m.group(1))
    for m in _RE_DB_QUERY.finditer(handler_body):
        _add(m.group(1))
    for m in _RE_SQL_TICK.finditer(handler_body):
        for sm in _RE_SCHEMA_ACCESS.finditer(m.group(1)):
            _add(sm.group(1))
    return tables


def _named_functions(src: str) -> dict[str, tuple[int, int]]:
    """Map named fn name -> (brace-open idx, brace-close idx).

    Covers `function NAME(...) {...}` and `const NAME = (async)? (...) => {...}`.
    """
    spans: dict[str, tuple[int, int]] = {}
    for m in re.finditer(r"\bfunction\s+(\w+)\s*\([^)]*\)\s*\{", src):
        close = _balance(src, m.end() - 1)
        if close > 0:
            spans[m.group(1)] = (m.end() - 1, close)
    for m in re.finditer(
        r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{", src
    ):
        close = _balance(src, m.end() - 1)
        if close > 0:
            spans[m.group(1)] = (m.end() - 1, close)
    return spans


def _enclosing(
    fn_spans: dict[str, tuple[int, int]],
    route_spans: list[tuple[str, int, int]],
    idx: int,
) -> str:
    """Function id (named fn or synthetic route_id) enclosing idx."""
    for name, (o, c) in fn_spans.items():
        if o <= idx <= c:
            return name
    for rid, o, c in route_spans:
        if o <= idx <= c:
            return rid
    return "<module>"


def _collect_rest(
    src: str, rel: str, name_map: dict[str, str], facts: CodeFacts
) -> None:
    """Pass 2: endpoints, attr accesses, raw_sql, calls."""
    fn_spans = _named_functions(src)
    # route_spans: (route_id, brace_open, brace_close)
    route_spans: list[tuple[str, int, int]] = []
    for m in _RE_ROUTE.finditer(src):
        method, path = m.group("method"), m.group("path")
        line = _line_of(src, m.start())
        rid = f"route_{line}"
        brace_open = src.find("{", m.end())
        close = _balance(src, brace_open) if brace_open != -1 else -1
        route_spans.append((rid, brace_open, close))
        facts.endpoints.append(EndpointFact(
            path=path, method=method, file=rel, line=line, function=rid,
        ))

    # attr accesses
    for m in _RE_SCHEMA_ACCESS.finditer(src):
        facts.attr_accesses.append(AttrAccess(
            model=m.group(1), column=m.group(2), file=rel,
            line=_line_of(src, m.start()),
            function=_enclosing(fn_spans, route_spans, m.start()),
        ))

    # raw-sql / table refs
    def _rawref(m: re.Match, tables: list[str]) -> None:
        facts.raw_sql.append(RawSqlRef(
            tables=tables, file=rel, line=_line_of(src, m.start()),
            function=_enclosing(fn_spans, route_spans, m.start()),
        ))

    for m in _RE_FROM_SCHEMA.finditer(src):
        _rawref(m, [name_map.get(m.group(1), m.group(1))])
    for m in _RE_TABLE_WRITE.finditer(src):
        _rawref(m, [name_map.get(m.group(1), m.group(1))])
    for m in _RE_DB_QUERY.finditer(src):
        _rawref(m, [name_map.get(m.group(1), m.group(1))])
    for m in _RE_SQL_TICK.finditer(src):
        tables = _resolve_tables(m.group(1), name_map)
        if tables:
            _rawref(m, tables)

    # calls: named foo(...) inside each named fn / route handler -> caller=callee
    all_spans: list[tuple[str, int, int]] = [(n, o, c) for n, (o, c) in fn_spans.items()]
    all_spans += [(rid, o, c) for rid, o, c in route_spans]
    for caller, o, c in all_spans:
        body = src[o:c] if c > 0 else ""
        for cm in _RE_CALL.finditer(body):
            callee = cm.group(1)
            if callee in fn_spans and callee != caller:
                facts.calls.append(FunctionCall(
                    caller=caller, callee=callee, file=rel,
                    line=_line_of(src, o + cm.start()),
                ))


def collect_facts_ts(app_dir: str) -> CodeFacts:
    root = Path(app_dir)
    facts = CodeFacts()
    name_map: dict[str, str] = {}
    # pass 1
    for f in _iter_ts(root):
        try:
            src = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(f.relative_to(root))
        name_map.update(_collect_models(src, rel, facts))
    # pass 2
    for f in _iter_ts(root):
        try:
            src = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(f.relative_to(root))
        _collect_rest(src, rel, name_map, facts)
    return facts
