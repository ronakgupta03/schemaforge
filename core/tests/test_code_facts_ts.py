from pathlib import Path

from schemaforge_core.code_facts_ts import collect_facts_ts

FIX = Path(__file__).parent / "fixtures" / "ts_app"


def test_models_with_sql_column_names():
    facts = collect_facts_ts(str(FIX))
    by_name = {m.name: m for m in facts.models}
    assert set(by_name) == {"users", "posts", "auditLog"}
    assert by_name["users"].table == "users"
    # SQL names (token_version, not the JS tokenVersion)
    assert "token_version" in by_name["users"].columns
    assert "email" in by_name["users"].columns
    # audit_log: id + payload (jsonb has an explicit name arg here)
    assert by_name["auditLog"].table == "audit_log"
    assert by_name["auditLog"].columns == ["id", "payload"]


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
    # a namespaced 3-part access (schema.auditLog.payload) must record the
    # Drizzle JS constant name (auditLog), not the SQL table name (audit_log),
    # so it keys into the impact-graph model node.
    assert ("auditLog", "payload") in acc


def test_from_clause_resolves_js_const_to_sql_table():
    facts = collect_facts_ts(str(FIX))
    tables_touched = {t for r in facts.raw_sql for t in r.tables}
    assert "posts" in tables_touched
    assert "users" in tables_touched


def test_calls_capture_named_helper():
    facts = collect_facts_ts(str(FIX))
    callers = {(c.caller, c.callee) for c in facts.calls}
    assert any(c[1] == "loadAuthor" for c in callers)


def test_endpoints_link_to_their_handler_accesses():
    # synthetic route function ids must match between EndpointFact.function and
    # the AttrAccess.function inside that handler, so the executes edge resolves.
    from schemaforge_core.impact_graph import build
    from schemaforge_core.models import ColumnInfo, DBSnapshot, TableInfo

    snap = DBSnapshot(tables={
        "users": TableInfo(name="users", columns=[
            ColumnInfo(name="email"), ColumnInfo(name="token_version"),
            ColumnInfo(name="username"), ColumnInfo(name="id"),
        ]),
        "posts": TableInfo(name="posts", columns=[
            ColumnInfo(name="published"), ColumnInfo(name="author_id"),
            ColumnInfo(name="title"), ColumnInfo(name="id"),
        ]),
        "audit_log": TableInfo(name="audit_log", columns=[
            ColumnInfo(name="payload"), ColumnInfo(name="id"),
        ]),
    })
    facts = collect_facts_ts(str(FIX))
    g = build(snap, facts)
    ep = next(n for n in g.nodes.values()
              if n.kind == "endpoint" and n.label == "get /api/posts")
    exec_targets = {e.dst for e in g.edges if e.src == ep.id and e.kind == "executes"}
    assert exec_targets, "get /api/posts must execute an attr/rawsql in its handler"


def test_post_endpoint_executes_helper_accesses_transitively():
    # the POST handler calls loadAuthor(); its schema.users.id/email accesses
    # must be reached via the call closure so the executes edge links them.
    from schemaforge_core.impact_graph import build
    from schemaforge_core.models import ColumnInfo, DBSnapshot, TableInfo

    snap = DBSnapshot(tables={
        "users": TableInfo(name="users", columns=[ColumnInfo(name="id"), ColumnInfo(name="email")]),
        "posts": TableInfo(name="posts", columns=[ColumnInfo(name="id")]),
        "audit_log": TableInfo(name="audit_log", columns=[ColumnInfo(name="id")]),
    })
    facts = collect_facts_ts(str(FIX))
    g = build(snap, facts)
    ep = next(n for n in g.nodes.values()
              if n.kind == "endpoint" and n.label == "post /api/posts")
    exec_targets = {e.dst for e in g.edges if e.src == ep.id and e.kind == "executes"}
    assert exec_targets, "post /api/posts must reach loadAuthor's accesses transitively"


def test_concise_handler_endpoint_executes():
    # a concise arrow handler (``c => expr`` with no block body) must still
    # produce an executes edge from its endpoint to the attr/rawsql it contains;
    # a brace search would mis-attribute it to <module> and miss the edge.
    from schemaforge_core.impact_graph import build
    from schemaforge_core.models import ColumnInfo, DBSnapshot, TableInfo

    snap = DBSnapshot(tables={
        "audit_log": TableInfo(name="audit_log", columns=[
            ColumnInfo(name="payload"), ColumnInfo(name="id"),
        ]),
    })
    facts = collect_facts_ts(str(FIX))
    g = build(snap, facts)
    ep = next(n for n in g.nodes.values()
              if n.kind == "endpoint" and n.label == "get /api/audit")
    exec_targets = {e.dst for e in g.edges if e.src == ep.id and e.kind == "executes"}
    assert exec_targets, "get /api/audit (concise handler) must execute an attr/rawsql"


def test_last_arg_start_ignores_template_literal_commas():
    from schemaforge_core.code_facts_ts import _last_arg_start
    # the last argument is the arrow handler 'c => ...', NOT split at the comma
    # inside the template literal or its ${} interpolation.
    inner = "'/x', c => sql`SELECT ${a.id}, literal`"
    start = _last_arg_start(inner)
    assert inner[start:].lstrip() == "c => sql`SELECT ${a.id}, literal`"
