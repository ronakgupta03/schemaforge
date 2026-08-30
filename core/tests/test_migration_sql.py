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

def test_expand_accepts_additive_alter(tmp_path):
    # Raw-SQL expand migrations legitimately ADD COLUMN / SET DEFAULT /
    # DROP NOT NULL / VALIDATE CONSTRAINT — metadata-only or brief on PG11+,
    # mirroring the Alembic op.* expand set and the MCP expand allowlist.
    body = ("ALTER TABLE users ADD COLUMN id_uuid uuid;\n"
            "ALTER TABLE users ALTER COLUMN id_uuid SET DEFAULT uuidv7();\n"
            "ALTER TABLE users ALTER COLUMN email DROP NOT NULL;\n"
            "ALTER TABLE orders ADD CONSTRAINT orders_user_fk FOREIGN KEY (user_id) "
            "REFERENCES users(id) NOT VALID;\n"
            "ALTER TABLE orders VALIDATE CONSTRAINT orders_user_fk;\n")
    validate_phase_sql(_write(tmp_path, body), "expand")  # must NOT raise


def test_contractive_alter_still_rejected_in_expand(tmp_path):
    p = _write(tmp_path, "ALTER TABLE users ALTER COLUMN email SET NOT NULL;\n")
    with pytest.raises(ValueError, match="contract ops"):
        validate_phase_sql(p, "expand")


def test_analyze_locks_set_default_is_brief(tmp_path):
    p = _write(tmp_path, "ALTER TABLE users ALTER COLUMN id SET DEFAULT uuidv7();\n")
    r = analyze_locks_sql(p)[0]
    assert r.risk == "brief-lock"
    assert r.rewrites is False


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
    assert r.rewrites is False  # PG11+ DROP COLUMN is metadata-only, no rewrite
    assert r.risk == "brief-lock"
    assert r.alternative  # non-empty online alternative


def test_analyze_locks_create_is_safe(tmp_path):
    p = _write(tmp_path, "CREATE TABLE t (id int);\n")
    reports = analyze_locks_sql(p)
    assert reports[0].lock == "none"
    assert reports[0].risk == "safe"


def test_analyze_locks_create_index_is_concurrent_candidate(tmp_path):
    # CREATE INDEX is not lock-free: it takes a Share lock; the safe form is
    # CREATE INDEX CONCURRENTLY (run outside execute_migration's transaction).
    p = _write(tmp_path, "CREATE INDEX idx_users_email ON users (email);\n")
    r = analyze_locks_sql(p)[0]
    assert r.lock == "Share"
    assert r.risk == "brief-lock"
    assert "CONCURRENTLY" in r.alternative


def test_analyze_locks_insert_select_backfill_is_heavy(tmp_path):
    # A large INSERT...SELECT backfill is not safe: it holds a Share lock on
    # the source table for the duration of the scan.
    p = _write(tmp_path, "INSERT INTO user_profiles (user_id) SELECT id FROM users;\n")
    r = analyze_locks_sql(p)[0]
    assert r.lock == "Share"
    assert r.risk == "dangerous"
    assert r.alternative


def test_block_comment_does_not_merge_tokens(tmp_path):
    # A comment between CREATE and TABLE must not collapse to "CREATETABLE",
    # which _sql_kind would reject as unclassified.
    p = _write(tmp_path, "CREATE/* note */TABLE t (id int);\n")
    cls = classify_sql(p)
    assert cls.expand and not cls.has_unclassified


def test_double_quote_identifier_not_split(tmp_path):
    # A ';' inside a double-quoted identifier must not terminate a statement;
    # the splitter yields two statements, not three.
    body = 'INSERT INTO "a;b" VALUES(1);\nCREATE TABLE t (id int);\n'
    cls = classify_sql(_write(tmp_path, body))
    assert len(cls.expand) == 2


def test_analyze_locks_add_column_volatile_default_is_heavy(tmp_path):
    # gen_random_uuid() is volatile, so ADD COLUMN ... DEFAULT forces a full
    # table+index rewrite on PG11+ -- flagged dangerous, not brief-lock.
    p = _write(tmp_path, "ALTER TABLE users ADD COLUMN uid text DEFAULT gen_random_uuid();\n")
    r = analyze_locks_sql(p)[0]
    assert r.lock == "AccessExclusive"
    assert r.rewrites is True
    assert r.risk == "dangerous"


def test_analyze_locks_add_column_stable_default_is_brief(tmp_path):
    # A constant/STABLE default is a PG11+ metadata-only fast default -- brief
    # lock, no rewrite.
    p = _write(tmp_path, "ALTER TABLE users ADD COLUMN c text DEFAULT 'x';\n")
    r = analyze_locks_sql(p)[0]
    assert r.risk == "brief-lock"
    assert r.rewrites is False


def test_analyze_locks_create_index_concurrently_is_online(tmp_path):
    # CONCURRENTLY does not block writes; it is 'online' (not brief-lock like a
    # plain CREATE INDEX) and applied outside the transaction by the verify path.
    p = _write(tmp_path, "CREATE INDEX CONCURRENTLY idx ON users (email);\n")
    r = analyze_locks_sql(p)[0]
    assert r.risk == "online"
    assert "CONCURRENTLY" in r.alternative


def test_analyze_locks_update_backfill_is_dangerous(tmp_path):
    # A large UPDATE backfill holds row locks for the whole transaction.
    p = _write(tmp_path, "UPDATE users SET address = 'x' WHERE address IS NULL;\n")
    r = analyze_locks_sql(p)[0]
    assert r.risk == "dangerous"
    assert r.alternative


def test_analyze_locks_alembic_version_update_is_safe(tmp_path):
    # The single-row alembic_version stamp is not a backfill.
    p = _write(tmp_path, "UPDATE alembic_version SET version_num = '0002';\n")
    r = analyze_locks_sql(p)[0]
    assert r.risk == "safe"
    assert not r.alternative


def test_analyze_locks_compound_volatile_default_is_heavy(tmp_path):
    # now() + random(): the compound expression is volatile because random()
    # is volatile, so ADD COLUMN forces a full rewrite -- not a fast default.
    p = _write(
        tmp_path,
        "ALTER TABLE users ADD COLUMN x timestamptz DEFAULT now() + random() * interval '1 second';\n",
    )
    r = analyze_locks_sql(p)[0]
    assert r.risk == "dangerous"
    assert r.rewrites is True


def test_analyze_locks_bare_stable_keyword_default_is_brief(tmp_path):
    # CURRENT_TIMESTAMP (no parens) is STABLE -> PG11+ metadata-only fast default.
    p = _write(tmp_path, "ALTER TABLE users ADD COLUMN created timestamptz DEFAULT CURRENT_TIMESTAMP;\n")
    r = analyze_locks_sql(p)[0]
    assert r.risk == "brief-lock"
    assert r.rewrites is False


def test_analyze_locks_stable_keyword_with_precision_is_brief(tmp_path):
    p = _write(tmp_path, "ALTER TABLE users ADD COLUMN created timestamptz DEFAULT CURRENT_TIMESTAMP(6);\n")
    r = analyze_locks_sql(p)[0]
    assert r.risk == "brief-lock"
    assert r.rewrites is False


def test_analyze_locks_stable_function_call_default_is_brief(tmp_path):
    # STABLE function calls with empty parens (statement_timestamp(), localtime())
    # are metadata-only fast defaults -- the function form resolves like the
    # bare keyword, not a volatile rewrite.
    for fn in ("statement_timestamp()", "localtime()"):
        p = tmp_path / f"mig_{fn.replace('(', '_').replace(')', '')}.sql"
        p.write_text(f"ALTER TABLE users ADD COLUMN x timestamptz DEFAULT {fn};\n")
        r = analyze_locks_sql(p)[0]
        assert r.risk == "brief-lock", fn
        assert r.rewrites is False, fn
