def test_render_json_shape():
    from schemaforge_core.report import render_json

    r = {
        "alembic_ok": True,
        "pytest_ok": True,
        "parity_ok": True,
        "diff": {"added_tables": ["user_profiles"], "removed_tables": [],
                 "added_columns": [], "removed_columns": ["users.address", "users.date_of_birth"]},
        "explain": [{"query": "find_by_email", "ms": 1.4, "ms_before": None}],
    }
    j = render_json(r)
    assert j["alembic_ok"] is True
    assert j["parity_ok"] is True
    assert j["diff"]["added_tables"] == ["user_profiles"]
    assert j["explain"][0]["query"] == "find_by_email"
    # machine-readable only — no markdown text
    assert "#" not in str(j)
