"""TDD tests for the contract gate (column-level reverse reachability)."""
import json
from pathlib import Path
from schemaforge_core.models import DBSnapshot, TableInfo, ColumnInfo, CodeFacts, ModelFact, AttrAccess
from schemaforge_core.impact_graph import build, impacted_by_columns


def _graph_with_access():
    """users.address is read by an attr access -> NOT safe to drop yet."""
    snap = DBSnapshot(tables={
        "users": TableInfo(name="users", columns=[
            ColumnInfo(name="id", type="integer", nullable=False),
            ColumnInfo(name="address", type="character varying", nullable=False),
        ]),
    })
    facts = CodeFacts(
        models=[ModelFact(name="User", table="users", columns=["id", "address"],
                          file="app/models.py", line=5)],
        attr_accesses=[AttrAccess(model="User", column="address",
                                  file="app/routers/reports.py", line=12, function="addresses_report")],
    )
    return build(snap, facts)


def _graph_without_access():
    """No code reads users.address -> safe to drop."""
    snap = DBSnapshot(tables={
        "users": TableInfo(name="users", columns=[
            ColumnInfo(name="id", type="integer", nullable=False),
            ColumnInfo(name="address", type="character varying", nullable=False),
        ]),
    })
    facts = CodeFacts(
        models=[ModelFact(name="User", table="users", columns=["id"],
                          file="app/models.py", line=5)],
    )  # no attr_accesses for address
    return build(snap, facts)


def test_contract_gate_blocked_when_code_reads_column():
    g = _graph_with_access()
    r = impacted_by_columns(g, ["users.address"])
    assert r["safe"] is False
    assert any(b["kind"] == "attr" and "address" in b["label"] for b in r["blockers"])
    assert "app/routers/reports.py" in r["files"]


def test_contract_gate_safe_when_no_code_reads_column():
    g = _graph_without_access()
    r = impacted_by_columns(g, ["users.address"])
    assert r["safe"] is True
    assert r["blockers"] == []


def test_contract_gate_unknown_column_is_blocked():
    # An unknown/typo column must BLOCK, not silently pass as SAFE — the
    # gate cannot prove a column it cannot see is safe to drop.
    g = _graph_without_access()
    r = impacted_by_columns(g, ["users.nonexistent"])
    assert r["safe"] is False
    assert r["absent"] == ["users.nonexistent"]
    assert any(b["kind"] == "absent" for b in r["blockers"])
