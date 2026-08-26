from pathlib import Path

from schemaforge_core.code_facts import collect_facts, _tables_from_sql

DEMO = Path(__file__).resolve().parents[2] / "demo-app"


def test_extracts_models():
    facts = collect_facts(str(DEMO))
    user = next(m for m in facts.models if m.name == "User")
    assert user.table == "users"
    assert set(user.columns) == {"id", "name", "email", "address", "date_of_birth"}
    book = next(m for m in facts.models if m.name == "Book")
    assert book.table == "books"


def test_extracts_attr_accesses():
    facts = collect_facts(str(DEMO))
    cols = {(a.model, a.column) for a in facts.attr_accesses}
    assert ("User", "address") in cols
    assert ("User", "date_of_birth") in cols


def test_extracts_raw_sql_tables():
    facts = collect_facts(str(DEMO))
    assert any("users" in r.tables for r in facts.raw_sql)


def test_extracts_calls():
    facts = collect_facts(str(DEMO))
    calls = {(c.caller, c.callee) for c in facts.calls}
    assert ("list_users", "to_out") in calls
    assert ("get_user", "to_out") in calls


def test_tables_from_sql():
    assert _tables_from_sql("SELECT u.name FROM users u WHERE u.id = 1") == ["users"]
    assert _tables_from_sql(
        "INSERT INTO user_profiles (user_id, address) SELECT id, address FROM users"
    ) == ["user_profiles", "users"]
    assert _tables_from_sql(
        "SELECT u.name, p.address FROM users u JOIN user_profiles p ON p.user_id = u.id"
    ) == ["users", "user_profiles"]
