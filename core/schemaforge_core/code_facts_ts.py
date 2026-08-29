"""Deterministic code facts from a TypeScript / Drizzle ORM source tree.

Generic over any Drizzle ORM app (pgTable/sqliteTable/mysqlTable) and any
Hono/Express-style router. Pure-Python static extraction — no tree-sitter, no
Node runtime. Column *types* are not parsed: they come from the live DB
snapshot. Two passes mirror the Python extractor (models first -> name map,
then endpoints/accesses/raw_sql/calls).

Three reference styles are resolved:
  * namespace — ``import * as schema``  ; ``schema.users.email``, ``.from(schema.users)``
  * direct     — ``import { users }``      ; ``users.email``, ``.from(users)``
  * aliased    — ``import { users as u }``; ``u.email``, ``.from(u)``
"""
from __future__ import annotations

import re
from pathlib import Path

from .models import (
    AttrAccess, CodeFacts, EndpointFact, FunctionCall, ModelFact, RawSqlRef,
)

_BUILDERS = ("pgTable", "sqliteTable", "mysqlTable")
_SKIP_DIRS = {"node_modules", "dist", "build", ".git", ".next", "coverage"}
_TS_SUFFIXES = (".ts", ".tsx")

# export const NAME = BUILDER('table', {  ... (capture up to the column-object '{')
_RE_MODEL = re.compile(
    r"export\s+const\s+(\w+)\s*=\s*(\w+Table)\s*\(\s*"
    r"(['\"])(?P<table>[^'\"]+)\3\s*,\s*\{"
)
# column key: builder('sqlname'   OR  key: builder() (no name)
_RE_COL_NAMED = re.compile(r"(\w+)\s*:\s*\w+\s*\(\s*(['\"])(?P<sql>[^'\"]+)\2")
_RE_COL_KEY = re.compile(r"(\w+)\s*:\s*")
# ROUTER.METHOD('/path', handler)  — any router var (Hono/Express)
_RE_ROUTE = re.compile(
    r"\b(\w+)\.(?P<method>get|post|put|patch|delete)\s*\(\s*"
    r"(['\"])(?P<path>[^'\"]+)\3\s*,"
)
# imports: named ({ a, b as c }) and namespace (* as ns)
_RE_IMPORT_NAMED = re.compile(r"import\s*\{([^}]*)\}")
_RE_IMPORT_NS = re.compile(r"import\s*\*\s*as\s+(\w+)\b")
# query args: .from(ARG) / .insert|update|delete(ARG)  — ARG may be schema.x or a bare ident
_RE_FROM = re.compile(r"\.from\(\s*([\w.]+)\s*\)")
_RE_WRITE = re.compile(r"\.(?:insert|update|delete)\(\s*([\w.]+)\s*\)")
_RE_DB_QUERY = re.compile(r"\bdb\.query\.(\w+)\b")
_RE_SQL_TICK = re.compile(r"sql`([^`]*)`")
# attribute access: NS.TABLE.COL (3-part) or TABLE.COL (2-part), leftmost-longest
_RE_ACCESS = re.compile(r"(\w+)\.(\w+)\.(\w+)|(\w+)\.(\w+)")
# named function call: foo(...) where foo is a declared function name
_RE_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")


def _iter_ts(root: Path):
    """Yield ``.ts`` and ``.tsx`` source files, skipping vendored dirs."""
    for p in sorted(root.rglob("*")):
        if p.suffix in _TS_SUFFIXES and not any(part in _SKIP_DIRS for part in p.parts):
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
    """SQL column names: first string arg of each TOP-LEVEL column builder,
    fallback the JS key.

    Only top-level properties of the table's column object are inspected (brace
    depth 0), so nested option objects such as ``{ length: 255 }`` are not
    mistaken for database columns.
    """
    named = {m.group(1): m.group("sql") for m in _RE_COL_NAMED.finditer(obj_body)}
    cols: list[str] = []
    seen: set[str] = set()
    depth = 0
    i = 0
    n = len(obj_body)
    while i < n:
        ch = obj_body[i]
        if ch == "{":
            depth += 1
            i += 1
        elif ch == "}":
            depth -= 1
            i += 1
        elif depth == 0 and (ch.isalnum() or ch == "_"):
            m = _RE_COL_KEY.match(obj_body, i)
            if m:
                key = m.group(1)
                sql = named.get(key, key)  # fallback to JS key when no name arg
                if sql not in seen:
                    seen.add(sql)
                    cols.append(sql)
                i = m.end()
            else:
                i += 1
        else:
            i += 1
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


def _parse_imports(src: str, name_map: dict[str, str]) -> tuple[dict[str, str], set[str]]:
    """Build (ident_map, namespaces) from a file's import statements.

    ``ident_map`` maps a local identifier to the original table jsname, but only
    for named imports whose original name is a known Drizzle table (in
    ``name_map``) — so unrelated imports (``eq``, ``sql``, ``Hono``) are ignored.
    ``namespaces`` is the set of ``import * as X`` names. The conventional
    ``schema`` namespace is always included so ``schema.X`` references resolve
    even when the import is implicit.
    """
    ident_map: dict[str, str] = {}
    namespaces: set[str] = {"schema"}
    for m in _RE_IMPORT_NS.finditer(src):
        namespaces.add(m.group(1))
    for m in _RE_IMPORT_NAMED.finditer(src):
        for item in m.group(1).split(","):
            item = item.strip()
            if not item:
                continue
            mm = re.match(r"(\w+)(?:\s+as\s+(\w+))?", item)
            if not mm:
                continue
            orig, local = mm.group(1), mm.group(2) or mm.group(1)
            if orig in name_map:
                ident_map[local] = orig
    return ident_map, namespaces


def _resolve_arg(arg: str, ident_map: dict[str, str],
                 name_map: dict[str, str], namespaces: set[str]) -> str:
    """Resolve a query argument (``schema.x`` or a bare identifier) to a SQL
    table name, or '' if it is not a known table."""
    arg = arg.strip()
    if not arg:
        return ""
    parts = arg.split(".")
    if len(parts) == 2 and parts[0] in namespaces:  # NS.TABLE
        return name_map.get(parts[1], parts[1])
    if len(parts) == 1:  # bare identifier (direct / aliased import)
        if arg in ident_map:
            return name_map.get(ident_map[arg], ident_map[arg])
        if arg in name_map:
            return name_map[arg]
    return ""


def _tables_in_text(text: str, ident_map: dict[str, str],
                    name_map: dict[str, str], namespaces: set[str]) -> list[str]:
    """All SQL tables referenced in a code or sql`` snippet (deduped, ordered)."""
    tables: list[str] = []
    seen: set[str] = set()

    def _add(t: str) -> None:
        if t and t not in seen:
            seen.add(t)
            tables.append(t)

    for m in _RE_FROM.finditer(text):
        _add(_resolve_arg(m.group(1), ident_map, name_map, namespaces))
    for m in _RE_WRITE.finditer(text):
        _add(_resolve_arg(m.group(1), ident_map, name_map, namespaces))
    for m in _RE_DB_QUERY.finditer(text):
        _add(name_map.get(m.group(1), m.group(1)))
    for m in _RE_ACCESS.finditer(text):
        if m.group(1):  # 3-part NS.TABLE.COL -> table is the 2nd component
            if m.group(1) in namespaces:
                _add(name_map.get(m.group(2), m.group(2)))
        else:  # 2-part TABLE.COL -> table is the 1st component
            t = m.group(4)
            if t in ident_map:
                _add(name_map.get(ident_map[t], ident_map[t]))
            elif t in name_map:
                _add(name_map[t])
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


def _scan_template(src: str, i: int) -> int:
    """Given ``i`` at an opening backtick, return the index just past the
    matching closing backtick of a TypeScript template literal, accounting for
    ``\\``` escapes and ``${ ... }`` interpolation (braces nest; nested template
    literals inside interpolation recurse)."""
    i += 1  # past the opening backtick
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == "\\":
            i += 2
        elif ch == "`":
            return i + 1
        elif ch == "$" and i + 1 < n and src[i + 1] == "{":
            i += 2  # past ${, enter interpolation
            depth = 1
            while i < n and depth > 0:
                c = src[i]
                if c == "{":
                    depth += 1
                    i += 1
                elif c == "}":
                    depth -= 1
                    i += 1
                elif c == "`":
                    i = _scan_template(src, i)  # nested template
                elif c == "\\":
                    i += 2
                else:
                    i += 1
        else:
            i += 1
    return n  # unterminated template; consume the rest


def _last_arg_start(args_text: str) -> int:
    """Index within ``args_text`` where the final top-level argument begins
    (right after the last depth-0 comma), or 0 for a single argument.

    Commas inside single/double-quoted strings and TypeScript template literals
    (`` `...${expr}...` ``) do not count as argument separators."""
    depth = 0
    last_comma = -1
    in_s = in_d = False
    i = 0
    n = len(args_text)
    while i < n:
        ch = args_text[i]
        if (in_s or in_d) and ch == "\\":
            i += 2          # skip escaped char inside a JS string
            continue
        if in_s:
            if ch == "'":
                in_s = False
        elif in_d:
            if ch == '"':
                in_d = False
        elif ch == "'":
            in_s = True
        elif ch == '"':
            in_d = True
        elif ch == "`":
            i = _scan_template(args_text, i) - 1  # -1: loop's i += 1
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            last_comma = i
        i += 1
    return last_comma + 1


def _last_arg(args_text: str) -> str:
    """Last top-level comma-separated argument of a call's argument list."""
    return args_text[_last_arg_start(args_text):].strip()


def _collect_rest(
    src: str, rel: str, name_map: dict[str, str], facts: CodeFacts
) -> None:
    """Pass 2: endpoints, attr accesses, raw_sql, calls."""
    fn_spans = _named_functions(src)
    ident_map, namespaces = _parse_imports(src, name_map)
    # route_spans: (route_id, brace_open, brace_close)
    route_spans: list[tuple[str, int, int]] = []
    for m in _RE_ROUTE.finditer(src):
        method, path = m.group("method"), m.group("path")
        line = _line_of(src, m.start())
        rid = f"route_{line}"
        # Resolve the route handler: the last argument of the route call.
        paren_open = src.find("(", m.start())
        paren_close = _balance(src, paren_open, "(", ")") if paren_open != -1 else -1
        handler = ""
        inner = ""
        if paren_close > 0:
            inner = src[m.end():paren_close]
            handler = _last_arg(inner)
        if re.fullmatch(r"\w+", handler) and handler in fn_spans:
            # named handler — reuse its body and link via a call edge
            o, c = fn_spans[handler]
            route_spans.append((rid, o, c))
            facts.calls.append(FunctionCall(
                caller=rid, callee=handler, file=rel, line=line,
            ))
        elif paren_close > 0:
            # inline callback (arrow expression or block) — span the final
            # argument, bounded by the route call's parentheses. Covers concise
            # arrows (``c => expr``) with no block body, which a brace search
            # would mis-attribute to <module>.
            a0 = m.end() + _last_arg_start(inner)
            route_spans.append((rid, a0, paren_close))
        else:
            route_spans.append((rid, -1, -1))
        facts.endpoints.append(EndpointFact(
            path=path, method=method, file=rel, line=line, function=rid,
        ))

    # attr accesses
    for m in _RE_ACCESS.finditer(src):
        if m.group(1):  # 3-part NS.TABLE.COL
            ns, tbl, col = m.group(1), m.group(2), m.group(3)
            if ns in namespaces:
                # AttrAccess.model is the Drizzle JS constant name (the key the
                # impact-graph model node uses), NOT the resolved SQL table name.
                facts.attr_accesses.append(AttrAccess(
                    model=tbl, column=col, file=rel,
                    line=_line_of(src, m.start()),
                    function=_enclosing(fn_spans, route_spans, m.start()),
                ))
        else:  # 2-part TABLE.COL
            t, col = m.group(4), m.group(5)
            if t in ident_map:
                model = ident_map[t]
            elif t in name_map:
                model = t
            else:
                continue
            facts.attr_accesses.append(AttrAccess(
                model=model, column=col, file=rel,
                line=_line_of(src, m.start()),
                function=_enclosing(fn_spans, route_spans, m.start()),
            ))

    # raw-sql / table refs
    def _rawref(m: re.Match, tables: list[str]) -> None:
        if not tables:
            return
        facts.raw_sql.append(RawSqlRef(
            tables=tables, file=rel, line=_line_of(src, m.start()),
            function=_enclosing(fn_spans, route_spans, m.start()),
        ))

    for m in _RE_FROM.finditer(src):
        _rawref(m, [_resolve_arg(m.group(1), ident_map, name_map, namespaces)])
    for m in _RE_WRITE.finditer(src):
        _rawref(m, [_resolve_arg(m.group(1), ident_map, name_map, namespaces)])
    for m in _RE_DB_QUERY.finditer(src):
        _rawref(m, [name_map.get(m.group(1), m.group(1))])
    for m in _RE_SQL_TICK.finditer(src):
        _rawref(m, _tables_in_text(m.group(1), ident_map, name_map, namespaces))

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
