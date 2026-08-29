def test_render_json_shape():
    from schemaforge_core.report import render_json

    r = {
        "tool": "alembic",
        "apply_ok": True,
        "test_ok": True,
        "parity_ok": True,
        "diff": {"added_tables": ["user_profiles"], "removed_tables": [],
                 "added_columns": [], "removed_columns": ["users.address", "users.date_of_birth"]},
        "explain": [{"query": "find_by_email", "ms": 1.4, "ms_before": None}],
    }
    j = render_json(r)
    assert j["apply_ok"] is True
    assert j["test_ok"] is True
    assert j["parity_ok"] is True

    # parity_ok passes through as-is — None must stay None, not become False
    j2 = render_json({"tool": "alembic", "apply_ok": True, "test_ok": True, "parity_ok": None})
    assert j2["parity_ok"] is None


def test_render_report_tool_aware_labels():
    from schemaforge_core.report import render_report

    alembic = render_report({"tool": "alembic", "apply_ok": True, "test_ok": True,
                             "parity_ok": None, "diff": {}, "explain": []})
    assert "Alembic migration" in alembic
    assert "alembic downgrade -1" in alembic

    sql = render_report({"tool": "sql", "apply_ok": True, "test_ok": True,
                         "parity_ok": None, "diff": {}, "explain": []})
    assert "SQL migration apply" in sql
    assert "Alembic" not in sql
    assert "revert script" in sql
