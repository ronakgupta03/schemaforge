import pytest

from schemaforge_core.migration_sql import (
    analyze_locks_sql,
    classify_sql,
    validate_phase_sql,
)


def _write(tmp_path, body, name="mig.sql"):
    p = tmp_path / name
    p.write_text(body)
    return str(p)


def test_expand_sql_classifies(tmp_path):
    p = _write(tmp_path,
               "CREATE TABLE user_profiles (id int);\n"
               "INSERT INTO user_profiles SELECT * FROM staging;\n")
    cls = classify_sql(p)
    assert cls.expand
    assert not cls.contract
    assert not cls.has_unclassified


def test_contract_sql_rejected_in_expand(tmp_path):
    p = _write(tmp_path, "ALTER TABLE users DROP COLUMN address;\n")
    with pytest.raises(ValueError, match="contract ops"):
        validate_phase_sql(p, "expand")


def test_contract_phase_accepts_alter(tmp_path):
    p = _write(tmp_path, "ALTER TABLE users DROP COLUMN address;\n")
    validate_phase_sql(p, "contract")  # must NOT raise


def test_contract_phase_rejects_expand(tmp_path):
    p = _write(tmp_path, "CREATE TABLE t (id int);\n")
    with pytest.raises(ValueError, match="expand ops"):
        validate_phase_sql(p, "contract")


def test_dollar_quote_not_split(tmp_path):
    body = ("CREATE FUNCTION f() RETURNS void AS $$ "
            "BEGIN SELECT 1; END $$ LANGUAGE plpgsql;\n"
            "CREATE TABLE t (id int);\n")
    cls = classify_sql(_write(tmp_path, body))
    assert len(cls.expand) == 2  # the inner ';' must not split the function body


def test_comment_semicolon_ignored(tmp_path):
    body = "-- a comment with a ; semicolon\nCREATE TABLE t (id int);\n"
    cls = classify_sql(_write(tmp_path, body))
    assert len(cls.expand) == 1


def test_block_comment_ignored(tmp_path):
    body = "/* block ; comment */\nCREATE TABLE t (id int);\n"
    cls = classify_sql(_write(tmp_path, body))
    assert len(cls.expand) == 1


def test_insert_select_backfill_is_expand(tmp_path):
    p = _write(tmp_path, "INSERT INTO user_profiles (user_id) SELECT id FROM users;\n")
    cls = classify_sql(p)
    assert cls.expand and not cls.contract


def test_analyze_locks_flags_alter(tmp_path):
    p = _write(tmp_path, "ALTER TABLE users DROP COLUMN address;\n")
    reports = analyze_locks_sql(p)
    assert len(reports) == 1
    r = reports[0]
    assert r.lock == "AccessExclusive"
    assert r.rewrites is True
    assert r.risk == "dangerous"
    assert r.alternative  # non-empty online alternative


def test_analyze_locks_create_is_safe(tmp_path):
    p = _write(tmp_path, "CREATE TABLE t (id int);\n")
    reports = analyze_locks_sql(p)
    assert reports[0].lock == "none"
    assert reports[0].risk == "safe"
