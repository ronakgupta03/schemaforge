# TypeScript / Drizzle ORM Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SchemaForge's deterministic core work on **any** TypeScript + Drizzle ORM app (any Postgres/SQLite/MySQL table builder, any Hono/Express-style router), not just Python/SQLAlchemy — generic, not tuned to one repo.

**Architecture:** Add a parallel static code-facts extractor (`code_facts_ts.py`) that emits the **same** `CodeFacts` dataclasses the Python path emits, so the entire downstream pipeline (`impact_graph`, `contract-gate`, `report`) is unchanged. Add a SQL-migration phase classifier (`migration_sql.py`) that reuses the already-written `_sql_kind` for raw-SQL migrations (Drizzle emits SQL, not Alembic `op.*`). Add language detection + dispatch in `cmd_facts`/`cmd_validate_phase`/`cmd_analyze_locks`/`cmd_verify`. Pure-Python static extraction — **no tree-sitter, no Node runtime** — matching the project's flat-dep philosophy. Column *types* are never parsed from code; they come from the live DB snapshot.

**Tech Stack:** Python 3.12+, `re`, stdlib only (no new deps). Drizzle ORM (`pgTable`/`sqliteTable`/`mysqlTable`), Hono/Express routes. Postgres via `psycopg`. Tests via `pytest`.

## Global Constraints

- **Generic, not repo-specific.** No hardcoded table/repo/revision literals. The extractor must work on any Drizzle app, not just TuxPages. Test fixtures are synthetic mini-apps, never the real repo.
- **Flat dependencies.** No tree-sitter, no Node/tsx, no new pip packages. Stdlib `re` + brace-balancing only. (The project deliberately dropped tree-sitter for Python; TS follows the same principle.)
- **Downstream unchanged.** `models.py` dataclasses, `impact_graph.py`, `contract-gate`, `report.py` are NOT modified. The TS path produces identical `CodeFacts`/`DBSnapshot` JSON shapes.
- **Column types come from the DB.** `ModelFact.columns` holds **SQL column names** (the first string arg of each Drizzle column builder, fallback the JS key). `AttrAccess.model` holds the **JS const name** (`schema.users`→`users`); `AttrAccess.column` holds the **JS property key** (label only — the graph links attr→model, not attr→column). JS-const → SQL-table resolution uses the model name map built in pass 1.
- **Reuse `_sql_kind`.** SQL-migration classification reuses `migration._sql_kind` (already written + tested) via a statement splitter; do not duplicate the verb taxonomy.
- **TDD + Qodo gate.** Every task: failing test → impl → pass → commit. Every substantive change ships via a Qodo-reviewed PR into `main`. Repo: `ronakgupta03/schemaforge`, default branch `main`.
- **Run tests via the venv:** `.vevn/bin/python -m pytest core/tests -q` (the eval kernel uses a different interpreter).

## File Structure

| File | Responsibility | Status |
|------|---------------|--------|
| `core/schemaforge_core/code_facts_ts.py` | NEW. Static TS/Drizzle facts extractor → `CodeFacts`. | create |
| `core/schemaforge_core/code_facts.py` | Python facts extractor. Unchanged. | — |
| `core/schemaforge_core/migration_sql.py` | NEW. SQL-migration phase classify/validate/locks reusing `_sql_kind`. | create |
| `core/schemaforge_core/migration.py` | Alembic classify/validate/locks. Unchanged (only imports `_sql_kind` for reuse). | — |
| `core/schemaforge_core/pipeline.py` | CLI dispatch: `cmd_facts`/`cmd_validate_phase`/`cmd_analyze_locks`/`cmd_verify` detect language. | modify |
| `core/schemaforge_core/detect.py` | NEW. Language + migration-tool detection (`detect_language(app_dir)`, `detect_migration_tool(app_dir)`). | create |
| `core/tests/test_code_facts_ts.py` | NEW. Extractor tests over synthetic fixtures. | create |
| `core/tests/fixtures/ts_app/` | NEW. Synthetic Drizzle+Hono mini-app (3 tables, FK, sub-fn, 2 routes). | create |
| `core/tests/test_migration_sql.py` | NEW. SQL phase classifier tests. | create |
| `core/tests/test_detect.py` | NEW. Detection tests. | create |
| `agent/instructions.md`, `skills/schemaforge-migration/SKILL.md` | Note TS/Drizzle support (prose only). | modify |

---

## Task 1: Language + migration-tool detection (`detect.py`)

**Files:**
- Create: `core/schemaforge_core/detect.py`
- Test: `core/tests/test_detect.py`

**Interfaces:**
- Produces: `detect_language(app_dir: str) -> str` → `"python" | "ts"`; `detect_migration_tool(app_dir: str) -> str` → `"alembic" | "sql" | "none"`.
- Detection rules:
  - `ts`: any `*.ts`/`*.tsx` file under `app_dir` (excl. `node_modules`, `dist`, `.git`) contains a Drizzle table-builder call (`pgTable(` / `sqliteTable(` / `mysqlTable(`).
  - `python`: otherwise, if an `alembic.ini` exists OR any `.py` file imports `sqlalchemy`/defines a declarative model.
  - `sql` migration tool: a `drizzle.config.ts` OR a `migrations/` (or `drizzle/`) dir with `*.sql`; `alembic`: `alembic.ini`; `none`: otherwise.

- [ ] **Step 1: Write failing tests**

```python
# core/tests/test_detect.py
from pathlib import Path
from schemaforge_core.detect import detect_language, detect_migration_tool


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_detect_ts_drizzle(tmp_path):
    _write(tmp_path, "src/db/schema.ts", "import { pgTable } from 'drizzle-orm';\n")
    _write(tmp_path, "src/server.ts", "export const x = pgTable('x', { id: serial('id') });\n")
    assert detect_language(str(tmp_path)) == "ts"
    assert detect_migration_tool(str(tmp_path)) == "none"


def test_detect_ts_with_migrations_dir(tmp_path):
    _write(tmp_path, "drizzle.config.ts", "export default {}\n")
    _write(tmp_path, "migrations/0001.sql", "CREATE TABLE t (id int);\n")
    _write(tmp_path, "src/schema.ts", "const u = pgTable('u',{id:serial('id')});\n")
    assert detect_migration_tool(str(tmp_path)) == "sql"


def test_detect_python(tmp_path):
    _write(tmp_path, "alembic.ini", "[alembic]\nscript_location = alembic\n")
    _write(tmp_path, "app/models.py", "from sqlalchemy import Column\n")
    assert detect_language(str(tmp_path)) == "python"
    assert detect_migration_tool(str(tmp_path)) == "alembic"


def test_detect_ignores_node_modules(tmp_path):
    _write(tmp_path, "node_modules/drizzle/schema.ts", "const u = pgTable('u',{id:serial('id')});\n")
    _write(tmp_path, "app/main.py", "print('hi')\n")
    # drizzle is inside node_modules (a vendored dep), not the app's own code
    assert detect_language(str(tmp_path)) == "python"
```

- [ ] **Step 2: Run — expect FAIL (`ModuleNotFoundError`)**

Run: `.vevn/bin/python -m pytest core/tests/test_detect.py -q`
Expected: FAIL `No module named schemaforge_core.detect`

- [ ] **Step 3: Implement**

```python
# core/schemaforge_core/detect.py
"""Language and migration-tool detection for a source tree."""
from __future__ import annotations
import re
from pathlib import Path

_DRIZZLE_BUILDER = re.compile(r"\b(?:pgTable|sqliteTable|mysqlTable)\s*\(")
_SKIP_DIRS = {"node_modules", "dist", "build", ".git", ".next", "coverage"}


def _iter_files(root: Path, suffix: str):
    for p in root.rglob(f"*{suffix}"):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        yield p


def detect_language(app_dir: str) -> str:
    root = Path(app_dir)
    for p in _iter_files(root, ".ts"):
        try:
            if _DRIZZLE_BUILDER.search(p.read_text(encoding="utf-8", errors="ignore")):
                return "ts"
        except OSError:
            continue
    if (root / "alembic.ini").exists():
        return "python"
    for p in _iter_files(root, ".py"):
        try:
            if "sqlalchemy" in p.read_text(encoding="utf-8", errors="ignore").lower():
                return "python"
        except OSError:
            continue
    # default: ts if any .ts exists, else python
    return "ts" if any(True for _ in _iter_files(root, ".ts")) else "python"


def detect_migration_tool(app_dir: str) -> str:
    root = Path(app_dir)
    if (root / "alembic.ini").exists():
        return "alembic"
    if (root / "drizzle.config.ts").exists():
        return "sql"
    for d in ("migrations", "drizzle"):
        dd = root / d
        if dd.is_dir() and any(dd.rglob("*.sql")):
            return "sql"
    return "none"
```

- [ ] **Step 4: Run — expect PASS**

Run: `.vevn/bin/python -m pytest core/tests/test_detect.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git checkout -b feat/ts-drizzle-support
git add core/schemaforge_core/detect.py core/tests/test_detect.py
git commit -m "feat(core): language + migration-tool detection"
```

---

## Task 2: TS/Drizzle code-facts extractor (`code_facts_ts.py`)

**Files:**
- Create: `core/schemaforge_core/code_facts_ts.py`
- Create: `core/tests/fixtures/ts_app/db/schema.ts`
- Create: `core/tests/fixtures/ts_app/server.ts`
- Test: `core/tests/test_code_facts_ts.py`

**Interfaces:**
- Consumes: `from .models import AttrAccess, CodeFacts, EndpointFact, FunctionCall, ModelFact, RawSqlRef`
- Produces: `collect_facts_ts(app_dir: str) -> CodeFacts` (same dataclasses the Python `collect_facts` returns).
- Extraction rules (generic):
  - **Models:** `export const NAME = <BUILDER>('table', { ... }, [config])` where `<BUILDER>` ∈ {pgTable, sqliteTable, mysqlTable}. `ModelFact.name`=JS const, `.table`=first string arg, `.columns`=SQL names (first string arg of each column builder; fallback the JS key). Build `jsname -> sqltable` map for pass 2.
  - **Endpoints:** `ROUTER.METHOD('/path', handler)` for METHOD ∈ {get,post,put,patch,delete}, any router var (Hono/Express). `EndpointFact.path`=path, `.method`=method, `.function`=synthetic `route_{line}`.
  - **AttrAccess:** `schema.<MODEL>.<COL>` (JS const + JS key). `.model`=JS const, `.column`=JS key, `.function`=enclosing route's synthetic id (or enclosing named function).
  - **RawSqlRef:** `.from(schema.<MODEL>)` and `db.query.<MODEL>` → tables resolved via the model map to SQL table names; `sql\`...\`` template literals → tables from any `schema.<M>` inside, resolved.
  - **FunctionCall:** named `foo(...)` calls within a function body (same-file transitive closure), same as Python path.
- **Two passes** (mirror Python): pass 1 models → name map; pass 2 endpoints/accesses/raw_sql/calls, resolving table names via the map.

- [ ] **Step 1: Create synthetic fixture (a generic mini Drizzle+Hono app)**

```typescript
// core/tests/fixtures/ts_app/db/schema.ts
import { pgTable, serial, varchar, integer, timestamp, boolean } from 'drizzle-orm';

export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  email: varchar('email', { length: 255 }).notNull(),
  username: varchar('username', { length: 50 }).notNull(),
  tokenVersion: integer('token_version').default(0).notNull(),
  createdAt: timestamp('created_at').defaultNow(),
});

export const posts = pgTable('posts', {
  id: serial('id').primaryKey(),
  authorId: integer('author_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  title: varchar('title', { length: 200 }).notNull(),
  published: boolean('published').default(false),
  createdAt: timestamp('created_at').defaultNow(),
});

export const auditLog = pgTable('audit_log', {
  id: serial('id').primaryKey(),
  // no SQL-name arg on this builder -> fallback to JS key
  payload: jsonb('payload'),
});
// jsonb import omitted on purpose: extractor must not require valid TS, only the table grammar
```

```typescript
// core/tests/fixtures/ts_app/server.ts
import { Hono } from 'hono';
import { eq, sql } from 'drizzle-orm';
import * as schema from './db/schema';

const app = new Hono();

function loadAuthor(authorId: number) {
  return app.db.select({ id: schema.users.id, email: schema.users.email })
    .from(schema.users).where(eq(schema.users.id, authorId)).limit(1);
}

app.get('/api/posts', async (c) => {
  const rows = await app.db.select().from(schema.posts).where(eq(schema.posts.published, true));
  return c.json(rows);
});

app.post('/api/posts', async (c) => {
  const author = loadAuthor(c.req.json('authorId'));
  const row = await app.db.insert(schema.posts).values({ authorId: author.id, title: 'x' });
  return c.json(row);
});

app.get('/api/users/:id', async (c) => {
  const u = await app.db.select().from(schema.users)
    .where(eq(sql`LOWER(${schema.users.username})`, c.req.param('id'))).limit(1);
  return c.json(u);
});

export default app;
```

- [ ] **Step 2: Write failing tests**

```python
# core/tests/test_code_facts_ts.py
import json
from pathlib import Path
from schemaforge_core.code_facts_ts import collect_facts_ts

FIX = Path(__file__).parent / "fixtures" / "ts_app"


def test_models_with_sql_column_names():
    facts = collect_facts_ts(str(FIX))
    by_name = {m.name: m for m in facts.models}
    assert set(by_name) == {"users", "posts", "auditLog"}
    assert by_name["users"].table == "users"
    # SQL names (token_version, not tokenVersion); createdAt has no name arg -> fallback key
    assert "token_version" in by_name["users"].columns
    assert "email" in by_name["users"].columns
    assert by_name["auditLog"].columns == ["payload"]


def test_endpoints_any_router_var():
    facts = collect_facts_ts(str(FIX))
    paths = {(e.method, e.path) for e in facts.endpoints}
    assert ("get", "/api/posts") in paths
    assert ("post", "/api/posts") in paths
    assert ("get", "/api/users/:id") in paths


def test_attr_accesses_use_js_const_and_key():
    facts = collect_facts_ts(str(FIX))
    acc = {(a.model, a.column) for a in facts.attr_accesses}
    assert ("users", "id") in acc
    assert ("users", "email") in acc
    assert ("posts", "published") in acc


def test_from_clause_resolves_js_const_to_sql_table():
    facts = collect_facts_ts(str(FIX))
    # .from(schema.posts) and .from(schema.users) become raw-sql refs with SQL table names
    tables_touched = {t for r in facts.raw_sql for t in r.tables}
    assert "posts" in tables_touched
    assert "users" in tables_touched


def test_calls_capture_named_helper():
    facts = collect_facts_ts(str(FIX))
    # the /api/posts POST handler calls loadAuthor(...)
    callers = {(c.caller, c.callee) for c in facts.calls}
    assert any(c[1] == "loadAuthor" for c in callers)


def test_endpoints_link_to_their_handler_accesses():
    # synthetic route function ids must match between EndpointFact.function
    # and the AttrAccess.function inside that handler, so the executes edge resolves.
    from schemaforge_core.impact_graph import build
    from schemaforge_core.models import DBSnapshot, TableInfo, ColumnInfo
    snap = DBSnapshot(tables={
        "users": TableInfo(name="users", columns=[ColumnInfo(name="email"), ColumnInfo(name="token_version"), ColumnInfo(name="username"), ColumnInfo(name="id")]),
        "posts": TableInfo(name="posts", columns=[ColumnInfo(name="published"), ColumnInfo(name="author_id"), ColumnInfo(name="title"), ColumnInfo(name="id")]),
        "audit_log": TableInfo(name="audit_log", columns=[ColumnInfo(name="payload"), ColumnInfo(name="id")]),
    })
    g = build(snap, facts)
    ep = next(n for n in g.nodes.values() if n.kind == "endpoint" and n.label == "get /api/posts")
    # endpoint executes an attr on posts.published (its handler)
    exec_targets = {e.dst for e in g.edges if e.src == ep.id and e.kind == "executes"}
    assert exec_targets, "get /api/posts must execute at least one attr/rawsql in its handler"
```

- [ ] **Step 3: Run — expect FAIL**

Run: `.vevn/bin/python -m pytest core/tests/test_code_facts_ts.py -q`
Expected: FAIL `No module named schemaforge_core.code_facts_ts`

- [ ] **Step 4: Implement `code_facts_ts.py`**

```python
# core/schemaforge_core/code_facts_ts.py
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
    AttrAccess, CodeFacts, EndpointFact, FunctionCall, ModelFact, RawSqlRef,
)

_BUILDERS = ("pgTable", "sqliteTable", "mysqlTable")
_METHODS = ("get", "post", "put", "patch", "delete")
_SKIP_DIRS = {"node_modules", "dist", "build", ".git", ".next", "coverage"}

# export const NAME = BUILDER('table', {  ... (capture up to the column-object '{')
_RE_MODEL = re.compile(
    r"export\s+const\s+(\w+)\s*=\s*(\w+Table)\s*\(\s*"
    r"(['\"])(?P<table>[^'\"]+)\3\s*,\s*\{"
)
# column key: builder('sqlname'   OR  key: builder() (no name)
_RE_COL_NAMED = re.compile(r"(\w+)\s*:\s*\w+\s*\(\s*(['\"])(?P<sql>[^'\"]+)\2")
_RE_COL_KEYS = re.compile(r"(\w+)\s*:\s*")
# ROUTER.METHOD('/path', handler)  — any router var
_RE_ROUTE = re.compile(
    r"\b(\w+)\.(?P<method>get|post|put|patch|delete)\s*\(\s*"
    r"(['\"])(?P<path>[^'\"]+)\3\s*,"
)
_RE_SCHEMA_ACCESS = re.compile(r"schema\.(\w+)\.(\w+)")
_RE_FROM_SCHEMA = re.compile(r"\.from\(\s*schema\.(\w+)\s*\)")
_RE_DB_QUERY = re.compile(r"\bdb\.query\.(\w+)\b")
_RE_SQL_TICK = re.compile(r"sql`([^`]*)`")
# named function call: foo(...) where foo is an identifier (not a keyword/builtin-ish)
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


def _resolve(handler_body: str, name_map: dict[str, str]) -> list[str]:
    """SQL table names touched in a handler body (.from(schema.X) / db.query.X / sql``)."""
    tables: list[str] = []
    seen: set[str] = set()
    for m in _RE_FROM_SCHEMA.finditer(handler_body):
        t = name_map.get(m.group(1), m.group(1))
        if t not in seen:
            seen.add(t); tables.append(t)
    for m in _RE_DB_QUERY.finditer(handler_body):
        t = name_map.get(m.group(1), m.group(1))
        if t not in seen:
            seen.add(t); tables.append(t)
    for m in _RE_SQL_TICK.finditer(handler_body):
        for sm in _RE_SCHEMA_ACCESS.finditer(m.group(1)):
            t = name_map.get(sm.group(1), sm.group(1))
            if t not in seen:
                seen.add(t); tables.append(t)
    return tables


def _named_functions(src: str) -> dict[str, tuple[int, int]]:
    """Map named function name -> (brace-open idx, brace-close idx) for
    `function NAME(...) {...}` and `const NAME = (...) => {...}` / `= async (...) =>`."""
    spans: dict[str, tuple[int, int]] = {}
    for m in re.finditer(r"\bfunction\s+(\w+)\s*\([^)]*\)\s*\{", src):
        close = _balance(src, m.end() - 1)
        if close > 0:
            spans[m.group(1)] = (m.end() - 1, close)
    for m in re.finditer(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{", src):
        close = _balance(src, m.end() - 1)
        if close > 0:
            spans[m.group(1)] = (m.end() - 1, close)
    return spans


def _enclosing(fn_spans: dict[str, tuple[int, int]], route_spans: list[tuple[str, int, int, int]],
               idx: int) -> str:
    """Return the function id (named fn or synthetic route_id) enclosing idx."""
    for name, (o, c) in fn_spans.items():
        if o <= idx <= c:
            return name
    for rid, o, c, _line in route_spans:
        if o <= idx <= c:
            return rid
    return "<module>"


def _collect_rest(src: str, rel: str, name_map: dict[str, str], facts: CodeFacts) -> None:
    """Pass 2: endpoints, attr accesses, raw_sql, calls."""
    fn_spans = _named_functions(src)
    route_spans: list[tuple[str, int, int, int]] = []  # (route_id, open, close, line)
    for m in _RE_ROUTE.finditer(src):
        method, path = m.group("method"), m.group("path")
        line = _line_of(src, m.start())
        rid = f"route_{line}"
        # handler body: first '{' at/after the comma following the path
        brace_open = src.find("{", m.end())
        close = _balance(src, brace_open) if brace_open != -1 else -1
        route_spans.append((rid, brace_open, close, line))
        facts.endpoints.append(EndpointFact(
            path=path, method=method, file=rel, line=line, function=rid,
        ))
    # attr accesses + raw_sql: walk every schema access / from / db.query / sql``
    for m in _RE_SCHEMA_ACCESS.finditer(src):
        facts.attr_accesses.append(AttrAccess(
            model=m.group(1), column=m.group(2), file=rel,
            line=_line_of(src, m.start()),
            function=_enclosing(fn_spans, route_spans, m.start()),
        ))
    for m in _RE_FROM_SCHEMA.finditer(src):
        t = name_map.get(m.group(1), m.group(1))
        facts.raw_sql.append(RawSqlRef(
            tables=[t], file=rel, line=_line_of(src, m.start()),
            function=_enclosing(fn_spans, route_spans, m.start()),
        ))
    for m in _RE_DB_QUERY.finditer(src):
        t = name_map.get(m.group(1), m.group(1))
        facts.raw_sql.append(RawSqlRef(
            tables=[t], file=rel, line=_line_of(src, m.start()),
            function=_enclosing(fn_spans, route_spans, m.start()),
        ))
    for m in _RE_SQL_TICK.finditer(src):
        tables = _resolve(m.group(1), name_map)
        if tables:
            facts.raw_sql.append(RawSqlRef(
                tables=tables, file=rel, line=_line_of(src, m.start()),
                function=_enclosing(fn_spans, route_spans, m.start()),
            ))
    # calls: named foo(...) inside each named fn / route handler -> caller=callee
    all_spans = [(n, o, c) for n, (o, c) in fn_spans.items()]
    all_spans += [(rid, o, c) for rid, o, c, _ in route_spans]
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
```

- [ ] **Step 5: Run — expect PASS**

Run: `.vevn/bin/python -m pytest core/tests/test_code_facts_ts.py -q`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add core/schemaforge_core/code_facts_ts.py core/tests/test_code_facts_ts.py core/tests/fixtures/ts_app/
git commit -m "feat(core): TS/Drizzle static code-facts extractor"
```

---

## Task 3: Wire `cmd_facts` language dispatch

**Files:**
- Modify: `core/schemaforge_core/pipeline.py:39-47` (`cmd_facts`)
- Modify: `core/schemaforge_core/pipeline.py:257-260` (facts subparser: add `--lang`)
- Test: extend `core/tests/test_code_facts_ts.py` with a CLI smoke test, OR `core/tests/test_pipeline_dispatch.py`

**Interfaces:**
- `cmd_facts` calls `detect_language(args.app)` (or uses `args.lang`) → `collect_facts` (python) or `collect_facts_ts` (ts).
- `--lang` arg: choices `auto|python|ts`, default `auto`.

- [ ] **Step 1: Write failing test**

```python
# core/tests/test_pipeline_dispatch.py
import json, subprocess, sys
from pathlib import Path
from schemaforge_core.pipeline import main

FIX = Path(__file__).parent / "fixtures" / "ts_app"


def test_cmd_facts_dispatches_ts(monkeypatch, tmp_path, capsys):
    out = tmp_path / "code.json"
    sys.argv = ["sf-pipeline", "facts", "--app", str(FIX), "--out", str(out)]
    main()
    data = json.loads(out.read_text())
    assert any(m["table"] == "posts" for m in data["models"])
    assert any(e["path"] == "/api/posts" for e in data["endpoints"])
```

- [ ] **Step 2: Run — expect FAIL (no `--lang`/dispatch; main parses but calls python `collect_facts` → 0 models)**

Run: `.vevn/bin/python -m pytest core/tests/test_pipeline_dispatch.py -q`
Expected: FAIL (assert 0 models)

- [ ] **Step 3: Implement dispatch**

Edit `pipeline.py` imports + `cmd_facts`:

```python
# add near top imports
from .code_facts import collect_facts
from .code_facts_ts import collect_facts_ts
from .detect import detect_language
```

Replace `cmd_facts` (lines 39-47):

```python
def cmd_facts(args: argparse.Namespace) -> None:
    lang = getattr(args, "lang", "auto") or "auto"
    if lang == "auto":
        lang = detect_language(args.app)
    facts = collect_facts_ts(args.app) if lang == "ts" else collect_facts(args.app)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(facts.to_dict(), indent=2))
    print(
        f"facts ({lang}) -> {args.out} ({len(facts.models)} models, "
        f"{len(facts.endpoints)} endpoints, {len(facts.attr_accesses)} attr accesses, "
        f"{len(facts.raw_sql)} raw-sql refs)"
    )
```

In the `facts` subparser (after `--out`):

```python
    s.add_argument("--lang", choices=["auto", "python", "ts"], default="auto")
```

- [ ] **Step 4: Run — expect PASS**

Run: `.vevn/bin/python -m pytest core/tests/test_pipeline_dispatch.py core/tests/test_code_facts.py -q`
Expected: all pass (no Python regression)

- [ ] **Step 5: Commit**

```bash
git add core/schemaforge_core/pipeline.py core/tests/test_pipeline_dispatch.py
git commit -m "feat(core): cmd_facts language dispatch (python|ts)"
```

---

## Task 4: SQL-migration phase classifier (`migration_sql.py`)

**Files:**
- Create: `core/schemaforge_core/migration_sql.py`
- Test: `core/tests/test_migration_sql.py`

**Interfaces:**
- Consumes: `from .migration import _sql_kind, OpClass, PhaseClassification, LockReport` (reuse `_sql_kind` + dataclasses).
- Produces: `classify_sql(file_path) -> PhaseClassification`; `validate_phase_sql(file_path, phase) -> None`; `analyze_locks_sql(file_path) -> list[LockReport]`.
- Statement splitter: split on `;` respecting single-quoted strings, double-quoted identifiers, `--`/`/* */` comments, and PostgreSQL dollar-quotes (`$tag$...$tag$`, `$$...$$`). (Reuse the postgres-mcp splitter approach; keep it simple + comment-aware.)
- `classify_sql`: for each statement, `_sql_kind(stmt)` → bucket into `PhaseClassification.expand/contract/neutral/unclassified`. `OpClass.source` = the statement text; `lineno` = first line of the statement in the file.
- `validate_phase_sql`: same purity rule as `validate_phase` (expand rejects contract; contract rejects expand; unclassified rejected).
- `analyze_locks_sql`: reuse `_lock_for` semantics by mapping the SQL verb to a lock reason (CREATE/INSERT → no lock; ALTER → AccessExclusive; DROP/TRUNCATE → AccessExclusive). A small `_lock_for_sql(stmt)` helper.

- [ ] **Step 1: Write failing tests**

```python
# core/tests/test_migration_sql.py
import pytest
from schemaforge_core.migration_sql import classify_sql, validate_phase_sql


def _write(tmp_path, body):
    p = tmp_path / "mig.sql"; p.write_text(body); return str(p)


def test_expand_sql_classifies(tmp_path):
    p = _write(tmp_path, "CREATE TABLE user_profiles (id int);\nINSERT INTO user_profiles SELECT * FROM staging;\n")
    cls = classify_sql(p)
    assert not cls.contract
    assert cls.expand
    assert not cls.has_unclassified


def test_contract_sql_rejected_in_expand(tmp_path):
    p = _write(tmp_path, "ALTER TABLE users DROP COLUMN address;\n")
    with pytest.raises(ValueError, match="contract ops"):
        validate_phase_sql(p, "expand")


def test_dollar_quote_not_split(tmp_path):
    body = "CREATE FUNCTION f() RETURNS void AS $$ BEGIN SELECT 1; END $$ LANGUAGE plpgsql;\nCREATE TABLE t (id int);\n"
    cls = classify_sql(p := _write(tmp_path, body))
    assert len(cls.expand) == 2  # the function body's ';' must not split it


def test_comment_semicolon_ignored(tmp_path):
    body = "-- a comment with a ; semicolon\nCREATE TABLE t (id int);\n"
    cls = classify_sql(p := _write(tmp_path, body))
    assert len(cls.expand) == 1
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.vevn/bin/python -m pytest core/tests/test_migration_sql.py -q`
Expected: FAIL `No module named schemaforge_core.migration_sql`

- [ ] **Step 3: Implement**

```python
# core/schemaforge_core/migration_sql.py
"""Phase classification, validation, and lock analysis for raw-SQL migrations
(Drizzle/psql), reusing migration._sql_kind for the verb taxonomy."""
from __future__ import annotations
import re
from pathlib import Path

from .migration import (
    OpClass, PhaseClassification, LockReport, _sql_kind, _lock_for,
)


def _split_sql_statements(src: str) -> list[tuple[int, str]]:
    """Split into (lineno, statement) on ';', honoring strings, comments, dollar-quotes."""
    stmts: list[tuple[int, str]] = []
    buf: list[str] = []
    line = 1
    stmt_start_line = 1
    i = 0
    n = len(src)
    in_s = in_d = False
    dollar = None  # current $tag$ or "$$"
    while i < n:
        ch = src[i]
        if in_s:
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and src[i + 1] == "'":
                    buf.append("'"); i += 2; continue
                in_s = False
        elif in_d:
            buf.append(ch)
            if ch == '"':
                in_d = False
        elif dollar is not None:
            buf.append(ch)
            if ch == "$":
                end = src.find(dollar, i)
                if end != -1:
                    buf.append(src[i + 1:end + len(dollar)])
                    i = end + len(dollar)
                    dollar = None
                    continue
        else:
            if ch == "'":
                in_s = True; buf.append(ch)
            elif ch == '"':
                in_d = True; buf.append(ch)
            elif ch == "-" and i + 1 < n and src[i + 1] == "-":
                nl = src.find("\n", i)
                if nl == -1:
                    break
                buf.append(src[i:nl]); i = nl; continue
            elif ch == "/" and i + 1 < n and src[i + 1] == "*":
                end = src.find("*/", i + 2)
                seg = src[i:end + 2] if end != -1 else src[i:]
                buf.append(seg); i = (end + 2) if end != -1 else n; continue
            elif ch == "$":
                m = re.match(r"\$(\w*)\$", src[i:])
                if m:
                    dollar = m.group(0)
                    buf.append(dollar); i += len(dollar); continue
                buf.append(ch)
            elif ch == ";":
                stmt = "".join(buf).strip()
                if stmt:
                    stmts.append((stmt_start_line, stmt))
                buf = []
                stmt_start_line = line + 1
            else:
                buf.append(ch)
                if ch == "\n":
                    line += 1
                    if not buf or all(c in " \t\r\n" for c in buf):
                        stmt_start_line = line
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append((stmt_start_line, tail))
    return stmts


def classify_sql(file_path: str | Path) -> PhaseClassification:
    src = Path(file_path).read_text()
    cls = PhaseClassification()
    for lineno, stmt in _split_sql_statements(src):
        kind, reason = _sql_kind(stmt)
        op = OpClass(source=stmt, kind=kind, reason=reason, lineno=lineno, end_lineno=lineno)
        getattr(cls, kind).append(op)
    return cls


def validate_phase_sql(file_path: str | Path, phase: str) -> None:
    if phase not in ("expand", "contract"):
        raise ValueError(f"phase must be 'expand' or 'contract', got {phase!r}")
    cls = classify_sql(file_path)
    if cls.has_unclassified:
        ops = ", ".join(f"L{o.lineno}: {o.reason}" for o in cls.unclassified)
        raise ValueError(f"unclassified statements — classify manually: {ops}")
    if phase == "expand" and cls.contract:
        ops = ", ".join(o.source.splitlines()[0] for o in cls.contract)
        raise ValueError(f"expand migration contains contract ops: {ops}")
    if phase == "contract" and cls.expand:
        ops = ", ".join(o.source.splitlines()[0] for o in cls.expand)
        raise ValueError(f"contract migration contains expand ops: {ops}")


def _lock_for_sql(stmt: str) -> tuple[str, bool, str, str]:
    head = stmt.lstrip().split(None, 1)[0].upper() if stmt.strip() else ""
    if head in ("CREATE", "INSERT"):
        return ("none", False, "additive — no blocking lock", "—")
    if head in ("ALTER", "DROP", "TRUNCATE"):
        return ("AccessExclusive", True, "blocks reads + writes", "expand/contract split + online tool (pg_repack)")
    return ("unknown", False, "unclassified", "review manually")


def analyze_locks_sql(file_path: str | Path) -> list[LockReport]:
    src = Path(file_path).read_text()
    reports: list[LockReport] = []
    for lineno, stmt in _split_sql_statements(src):
        lock, rewrites, risk, alt = _lock_for_sql(stmt)
        reports.append(LockReport(
            statement=stmt.splitlines()[0][:120], lock=lock,
            rewrites=rewrites, risk=risk, reason=alt,
        ))
    return reports
```

- [ ] **Step 4: Run — expect PASS**

Run: `.vevn/bin/python -m pytest core/tests/test_migration_sql.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add core/schemaforge_core/migration_sql.py core/tests/test_migration_sql.py
git commit -m "feat(core): SQL-migration phase classifier (reuses _sql_kind)"
```

---

## Task 5: Wire `validate-phase` / `analyze-locks` SQL dispatch

**Files:**
- Modify: `core/schemaforge_core/pipeline.py:76-83` (`cmd_validate_phase`)
- Modify: `core/schemaforge_core/pipeline.py:102-117` (`cmd_analyze_locks`)

**Interfaces:**
- Dispatch on the migration file extension: `.sql` → `migration_sql.*`; `.py` → `migration.*`.

- [ ] **Step 1: Write failing test**

```python
# core/tests/test_pipeline_dispatch.py  (append)
def test_validate_phase_dispatches_sql(tmp_path):
    import sys
    from schemaforge_core.pipeline import main
    p = tmp_path / "mig.sql"; p.write_text("ALTER TABLE users DROP COLUMN address;\n")
    sys.argv = ["sf-pipeline", "validate-phase", "--migration", str(p), "--phase", "contract"]
    main()  # should NOT raise (contract phase accepts the ALTER)
```

- [ ] **Step 2: Run — expect FAIL (currently routes .sql through Alembic `classify` → no upgrade() → ValueError)**

- [ ] **Step 3: Implement**

```python
# pipeline.py cmd_validate_phase
def cmd_validate_phase(args: argparse.Namespace) -> None:
    path = Path(args.migration)
    if path.suffix == ".sql":
        from .migration_sql import validate_phase_sql
        validate_fn = validate_phase_sql
    else:
        from .migration import validate_phase
        validate_fn = validate_phase
    try:
        validate_fn(args.migration, args.phase)
        print(f"{args.migration}: phase='{args.phase}' OK")
    except ValueError as e:
        print(f"{args.migration}: {e}", file=sys.stderr)
        raise SystemExit(1)
```

```python
# pipeline.py cmd_analyze_locks
def cmd_analyze_locks(args: argparse.Namespace) -> None:
    path = Path(args.migration)
    if path.suffix == ".sql":
        from .migration_sql import analyze_locks_sql
        reports = analyze_locks_sql(args.migration)
    else:
        from .migration import analyze_locks
        reports = analyze_locks(args.migration)
    for r in reports:
        print(f"  {r.statement}")
        print(f"    lock={r.lock} rewrites={r.rewrites} risk={r.risk}")
        if r.reason:
            print(f"      -> {r.reason}")
    if args.out:
        import json
        Path(args.out).write_text(json.dumps([r.__dict__ for r in reports], indent=2))
```

- [ ] **Step 4: Run — expect PASS**

Run: `.vevn/bin/python -m pytest core/tests/test_pipeline_dispatch.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add core/schemaforge_core/pipeline.py core/tests/test_pipeline_dispatch.py
git commit -m "feat(core): validate-phase/analyze-locks SQL dispatch"
```

---

## Task 6: `verify` TS path + docs

**Files:**
- Modify: `core/schemaforge_core/pipeline.py:152-214` (`cmd_verify`)
- Modify: `agent/instructions.md`, `skills/schemaforge-migration/SKILL.md` (prose only)

**Interfaces:**
- `cmd_verify` detects migration tool via `detect_migration_tool(args.dir)`:
  - `alembic`: existing path (`alembic upgrade head` + `pytest` + parity + explain).
  - `sql`: apply migrations via `psql -f` in order (or a single `--migration` arg), then `parity.sql` + explain. Contract tests via `npm test` if a `package.json` test script exists, else parity is the sole invariant (skip pytest, do not fail on its absence).
- Keep parity.sql + explain logic unchanged (language-agnostic).

- [ ] **Step 1: Write failing test**

```python
# core/tests/test_pipeline_dispatch.py (append)
def test_verify_sql_path_skips_alembic_when_no_alembic_ini(tmp_path, monkeypatch):
    import sys, json
    from schemaforge_core import pipeline
    # a fake dsn we won't really connect to; stub connect/snapshot
    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def execute(self, sql): return []
    monkeypatch.setattr(pipeline, "connect", lambda dsn: FakeConn())
    monkeypatch.setattr(pipeline, "snapshot", lambda conn: pipeline.DBSnapshot())
    # no alembic.ini, no package.json -> sql path, parity-only
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001.sql").write_text("CREATE TABLE t (id int);\n")
    out = tmp_path / "report.md"
    sys.argv = ["sf-pipeline", "verify", "--dir", str(tmp_path), "--dsn",
                "postgresql://x@localhost/x", "--baseline", str(tmp_path / "b.json"),
                "--queries", str(tmp_path / "q.sql"), "--out", str(out)]
    (tmp_path / "b.json").write_text(json.dumps({"tables": {}}))
    (tmp_path / "q.sql").write_text("SELECT 1;")
    # should not raise SystemExit(1) over a missing alembic/pytest
    pipeline.main()
```

- [ ] **Step 2: Run — expect FAIL (current `cmd_verify` always runs alembic+pytest)**

- [ ] **Step 3: Implement (add a `--tool` arg + branch; keep alembic path as the default)**

In the `verify` subparser add `s.add_argument("--tool", choices=["auto", "alembic", "sql"], default="auto")`.

Refactor `cmd_verify` to branch on tool. Preserve the existing alembic block verbatim under `if tool in ("alembic",) or (tool == "auto" and mig == "alembic")`. The `sql` branch:

```python
    mig = detect_migration_tool(args.dir) if args.tool == "auto" else args.tool
    if mig == "sql":
        # apply migrations in lexicographic order via psql
        mdir = Path(args.dir) / "migrations"
        sqls = sorted(mdir.glob("*.sql")) if mdir.is_dir() else []
        apply_ok, apply_out = True, ""
        for sf in sqls:
            r = _run(["psql", "-v", "ON_ERROR_STOP=1", "-f", str(sf), args.dsn], Path(args.dir), env)
            apply_ok = apply_ok and r.returncode == 0
            apply_out += r.stdout + r.stderr
        # parity + explain (reuse existing parity/explain block)
        # contract tests: npm test if package.json with a test script, else parity-only
        pkg = Path(args.dir) / "package.json"
        test_ok, test_out = True, ""
        if pkg.exists():
            import json as _j
            if _j.loads(pkg.read_text()).get("scripts", {}).get("test"):
                r = _run(["npm", "test", "--silent"], Path(args.dir), env)
                test_ok = r.returncode == 0
                test_out = (r.stdout + r.stderr)[-3000:]
        # ... assemble result dict with apply_ok/test_ok/parity_ok/diff/explain ...
        sys.exit(0 if (apply_ok and test_ok and parity_ok is not False) else 1)
    else:
        # existing alembic path (unchanged)
        ...
```

(Implement the full assembly by reusing the existing parity/explain blocks; do not duplicate the parity SQL logic.)

- [ ] **Step 4: Run — expect PASS**

Run: `.vevn/bin/python -m pytest core/tests/test_pipeline_dispatch.py core/tests -q`
Expected: all pass (no Python-path regression; the demo-app alembic path still works when `--tool auto` finds `alembic.ini`)

- [ ] **Step 5: Docs (prose only — no config restatement)**

In `agent/instructions.md` and `skills/schemaforge-migration/SKILL.md`, add one line each in the bootstrap/facts step: "The pipeline auto-detects Python/SQLAlchemy or TypeScript/Drizzle; for TS apps it extracts facts from `pgTable`/`sqliteTable`/`mysqlTable` + Hono/Express routes, and classifies raw-SQL migrations by SQL verb (no Alembic `op.*` needed)."

- [ ] **Step 6: Commit**

```bash
git add core/schemaforge_core/pipeline.py core/tests/test_pipeline_dispatch.py agent/instructions.md skills/schemaforge-migration/SKILL.md
git commit -m "feat(core): verify TS path (psql apply + parity) + docs"
```

---

## Self-Review

**Spec coverage:**
- Generic TS/Drizzle facts → Task 2 (extractor) + Task 3 (dispatch). ✓
- Any router var / Drizzle builder → `_RE_ROUTE` (any `\w+.`) + `_BUILDERS` set. ✓
- SQL-migration phase classify → Task 4 + Task 5. ✓
- verify on TS (psql + parity) → Task 6. ✓
- No repo-specific literals → all tests use synthetic `ts_app` fixture; no TuxPages references. ✓
- Downstream unchanged → no edits to `models.py`/`impact_graph.py`/`report.py`. ✓
- Flat deps → stdlib `re` only. ✓

**Known limitations (documented, graceful — not crashes):**
- `app.route('/prefix', subRouter)` mounting does not prefix sub-routes (sub-routes are still found as endpoints at their own paths). TuxPages does not use this; common Drizzle apps mostly use flat `app.METHOD`. A later hardening pass can resolve prefixes.
- Drizzle relational-query `db.query.X` is captured as a table read (RawSqlRef), not column-level accesses (the relational API hides columns). Column-level reachability still works via `schema.X.Y` accesses; `db.query.X` gives table-level only.
- Column builders without a name arg fall back to the JS key as the SQL name (Drizzle's default behavior).

**Type consistency:** `collect_facts_ts` returns `CodeFacts`; `classify_sql` returns `PhaseClassification` (same dataclass as `classify`); `validate_phase_sql`/`analyze_locks_sql` mirror `validate_phase`/`analyze_locks` signatures. `cmd_facts`/`cmd_validate_phase`/`cmd_analyze_locks` branch on the same `detect_language`/file-suffix signals.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-30-ts-drizzle-support.md`. Recommended: **inline execution** (deadline day; I own git + tests + Qodo PRs). Each task ends with a commit; the branch `feat/ts-drizzle-support` ships as a single Qodo-reviewed PR into `main` (or split into 2 PRs if Qodo flags too much at once).
