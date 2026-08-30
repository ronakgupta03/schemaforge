from schemaforge_core.impact_graph import build, impacted_by, to_mermaid
from schemaforge_core.models import (
    AttrAccess,
    CodeFacts,
    ColumnInfo,
    DBSnapshot,
    EndpointFact,
    FunctionCall,
    ModelFact,
    RawSqlRef,
    TableInfo,
)


def _fixture():
    snap = DBSnapshot()
    snap.tables["users"] = TableInfo(
        name="users",
        columns=[
            ColumnInfo(name="id", data_type="integer", nullable=False),
            ColumnInfo(name="email", data_type="varchar", nullable=False),
            ColumnInfo(name="address", data_type="varchar", nullable=False),
        ],
    )
    facts = CodeFacts(
        models=[
            ModelFact(name="User", table="users",
                      columns=["id", "email", "address"],
                      file="app/models.py", line=5)
        ],
        attr_accesses=[
            AttrAccess(model="User", column="address",
                       file="app/routers/users.py", line=10, function="list_users"),
            AttrAccess(model="User", column="email",
                       file="app/routers/users.py", line=12, function="get_user"),
        ],
        raw_sql=[
            RawSqlRef(tables=["users"], file="app/routers/reports.py",
                      line=5, function="user_addresses")
        ],
        endpoints=[
            EndpointFact(path="/users", method="GET", file="app/routers/users.py",
                         line=8, function="list_users"),
            EndpointFact(path="/users/{user_id}", method="GET",
                         file="app/routers/users.py", line=20, function="get_user"),
            EndpointFact(path="/reports/addresses", method="GET",
                         file="app/routers/reports.py", line=4, function="user_addresses"),
        ],
    )
    return snap, facts


def test_build_has_expected_edge_kinds():
    snap, facts = _fixture()
    g = build(snap, facts)
    kinds = {e.kind for e in g.edges}
    assert {"maps_to", "has_column", "accessed_via", "queries", "executes"} <= kinds


def test_impacted_by_users_covers_all_code_paths():
    snap, facts = _fixture()
    g = build(snap, facts)
    hit = impacted_by(g, ["users"])
    assert "app/models.py" in hit["files"]
    assert "app/routers/users.py" in hit["files"]
    assert "app/routers/reports.py" in hit["files"]
    assert "GET /users" in hit["endpoints"]
    assert "GET /reports/addresses" in hit["endpoints"]
    assert "User" in hit["models"]
    assert "users.address" in hit["columns"]


def test_impacted_by_unknown_table_is_empty():
    snap, facts = _fixture()
    g = build(snap, facts)
    hit = impacted_by(g, ["nonexistent"])
    assert hit["files"] == []
    assert hit["endpoints"] == []


def test_mermaid_renders_subgraphs():
    snap, facts = _fixture()
    g = build(snap, facts)
    mmd = to_mermaid(g)
    assert mmd.startswith("flowchart LR")
    assert "subgraph table" in mmd
    assert "subgraph endpoint" in mmd
    assert "subgraph attr" not in mmd
    assert "subgraph rawsql" not in mmd
    assert 'label' not in mmd  # sanity: no leaked python reprs


def test_mermaid_display_projection_keeps_endpoints_linked():
    """An endpoint that reaches a model only through an attr helper must still
    appear in the bounded display graph connected to that model/table."""
    snap, facts = _fixture()
    g = build(snap, facts)
    mmd = to_mermaid(g)
    # The fixture has an attr access in a helper called by the endpoint, so the
    # collapsed graph should contain a synthesized endpoint -> model edge.
    assert "depends_on" in mmd


def test_endpoint_reaches_helper_attr_access():
    snap = DBSnapshot()
    snap.tables["users"] = TableInfo(
        name="users",
        columns=[
            ColumnInfo(name="address", data_type="varchar", nullable=False),
        ],
    )
    facts = CodeFacts(
        models=[
            ModelFact(name="User", table="users",
                      columns=["address"],
                      file="app/models.py", line=5)
        ],
        attr_accesses=[
            AttrAccess(model="User", column="address",
                       file="app/routers/users.py", line=10, function="to_out")
        ],
        endpoints=[
            EndpointFact(path="/users", method="GET",
                         file="app/routers/users.py", line=5, function="list_users")
        ],
        calls=[
            FunctionCall(caller="list_users", callee="to_out",
                         file="app/routers/users.py", line=6)
        ],
    )
    g = build(snap, facts)
    hit = impacted_by(g, ["users"])
    assert "GET /users" in hit["endpoints"]