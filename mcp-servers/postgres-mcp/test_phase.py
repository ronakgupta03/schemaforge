"""Functional test: execute_migration(phase='expand') rejects non-additive verbs.

The expand guard is an ALLOWLIST, not a denylist: only additive statements
(CREATE, INSERT backfill, UPDATE alembic_version, UPDATE backfill of
columns the batch ADDed, ADD COLUMN/CONSTRAINT, ALTER COLUMN SET DEFAULT,
VALIDATE CONSTRAINT) pass; everything else is rejected so a mis-authored
expand fails safely rather than modifying existing objects. This keeps the
test hermetic: no real DB is touched.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import server  # noqa: E402
from server import (  # noqa: E402
    execute_migration,
    _is_expand_allowed,
    _validate_migration_statement,
    _added_columns,
)


class _MockConn:
    """Stand-in for _conn: additive batches that pass the guard reach here."""

    def __enter__(self):
        return self
    def __init__(self, autocommit: bool = True):
        pass
    def __exit__(self, *exc):
        return False

    def execute(self, stmt):
        raise RuntimeError("mock-no-db")

    def commit(self):
        raise RuntimeError("mock-no-db")

    def rollback(self):
        pass


server._conn = _MockConn  # hermetic: never touch a real DB


# --- 1. allowlist: non-additive rejected, additive accepted ---
# Non-additive (rejected in expand) — the exotic ALTER cases Qodo flagged:
assert _is_expand_allowed("DROP TABLE users") is not None
assert _is_expand_allowed("DROP INDEX users_email") is not None
assert _is_expand_allowed("ALTER TABLE users DROP COLUMN address") is not None
assert _is_expand_allowed("TRUNCATE TABLE users") is not None
assert _is_expand_allowed("ALTER TABLE users ALTER COLUMN address SET NOT NULL") is not None
assert _is_expand_allowed("ALTER TABLE users ALTER COLUMN address TYPE bigint") is not None
# Non-additive ALTER that a denylist would miss (Qodo finding):
assert _is_expand_allowed("ALTER TABLE users RENAME TO accounts") is not None
assert _is_expand_allowed("ALTER TABLE users SET TABLESPACE fast") is not None
assert _is_expand_allowed("ALTER TABLE users ENABLE TRIGGER ALL") is not None
assert _is_expand_allowed("ALTER TABLE users DISABLE TRIGGER ALL") is not None
assert _is_expand_allowed("ALTER TABLE users OWNER TO app") is not None
assert _is_expand_allowed("ALTER TABLE users SET (fillfactor=90)") is not None
# Non-ALTER non-additive verbs:
assert _is_expand_allowed("DELETE FROM users") is not None
assert _is_expand_allowed("UPDATE users SET name='x'") is not None
assert _is_expand_allowed("SELECT 1") is not None
# Additive (allowed in expand) — None means accepted:
assert _is_expand_allowed("CREATE TABLE user_profiles (id int)") is None
assert _is_expand_allowed(
    "CREATE INDEX CONCURRENTLY ix_users_email ON users(email)"
) is None
assert _is_expand_allowed("INSERT INTO user_profiles (a) SELECT a FROM users") is None
assert _is_expand_allowed("UPDATE alembic_version SET version_num='0002'") is None
assert _is_expand_allowed("ALTER TABLE users ADD COLUMN x int") is None
assert _is_expand_allowed("ALTER TABLE users ADD COLUMN x int NOT NULL DEFAULT 0") is None
assert _is_expand_allowed("ALTER TABLE users ADD CONSTRAINT chk CHECK (x > 0)") is None
assert _is_expand_allowed(
    "ALTER TABLE users ADD CONSTRAINT fk FOREIGN KEY (uid) REFERENCES users(id)"
) is None
assert _is_expand_allowed("ALTER TABLE users ALTER COLUMN address SET DEFAULT ''") is None
# DROP NOT NULL is a constraint RELAXATION (expand-safe): it lets the next app
# build insert rows without the legacy column during the expand->contract window.
assert _is_expand_allowed("ALTER TABLE users ALTER COLUMN address DROP NOT NULL") is None
assert _is_expand_allowed("ALTER TABLE users\n  ALTER COLUMN address DROP NOT NULL") is None
# SET NOT NULL is a contraction (still rejected):
assert _is_expand_allowed("ALTER TABLE users ALTER COLUMN address SET NOT NULL") is not None
# Multi-action smuggling: an additive DROP NOT NULL must NOT mask a destructive
# DROP COLUMN smuggled in the same ALTER statement (Qodo finding).
assert _is_expand_allowed(
    "ALTER TABLE users ALTER COLUMN address DROP NOT NULL, DROP COLUMN email"
) is not None
assert _is_expand_allowed(
    "ALTER TABLE users ADD COLUMN x int, DROP COLUMN y int"
) is not None
assert _is_expand_allowed("ALTER TABLE users VALIDATE CONSTRAINT chk") is None
# multi-line additive statement (regex must span newlines for the ALTER clause)
assert _is_expand_allowed("ALTER TABLE users\n  ADD COLUMN x int") is None
# --- 1b. UPDATE backfill: SET columns must be ADDed by the batch ---
_ADDED_USERS = {"users": {"id_uuid"}}
assert _is_expand_allowed("UPDATE users SET id_uuid = gen_random_uuid()", _ADDED_USERS) is None
assert _is_expand_allowed(
    "UPDATE users SET id_uuid = gen_random_uuid() WHERE id_uuid IS NULL", _ADDED_USERS
) is None
assert _is_expand_allowed(
    "UPDATE users SET id_uuid = 1, slug = lower(name)", {"users": {"id_uuid", "slug"}}
) is None
assert _is_expand_allowed(
    "UPDATE users SET note = 'a,b', id_uuid = 1", {"users": {"id_uuid", "note"}}
) is None  # comma inside a string literal is not a SET separator
assert _is_expand_allowed(
    'UPDATE users SET "IdUuid" = gen_random_uuid()', {"users": {"iduuid"}}
) is None  # quoted identifiers are normalized
# pre-existing / smuggled / wrong-table columns stay rejected:
assert _is_expand_allowed("UPDATE users SET name = 'x'", _ADDED_USERS) is not None
assert _is_expand_allowed("UPDATE users SET id_uuid = 1, email = 'x'", _ADDED_USERS) is not None
assert _is_expand_allowed("UPDATE blogs SET id_uuid = 1", _ADDED_USERS) is not None
assert _is_expand_allowed("UPDATE users SET id_uuid = 1", None) is not None  # no batch context

# --- 1c. _added_columns: ADD COLUMN tracking, clause starters excluded ---
assert _added_columns(["ALTER TABLE users ADD COLUMN id_uuid uuid"]) == {"users": {"id_uuid"}}
assert _added_columns(
    [
        "ALTER TABLE users ADD COLUMN a int, ADD COLUMN b text",
        "ALTER TABLE users ADD CONSTRAINT chk CHECK (a > 0)",
    ]
) == {"users": {"a", "b"}}
assert _added_columns(
    ["ALTER TABLE users ADD COLUMN note text DEFAULT 'ADD COLUMN foo'"]
) == {"users": {"note"}}  # words inside string literals are not ADD COLUMNs
assert _added_columns(["CREATE TABLE t (id int)"]) == {}

# --- 1d. _validate_migration_statement: backfill UPDATE needs batch context ---
_validate_migration_statement(
    "UPDATE users SET id_uuid = gen_random_uuid()", {"users": {"id_uuid"}}
)
try:
    _validate_migration_statement("UPDATE users SET email = 'x'", {"users": {"id_uuid"}})
except ValueError as e:
    assert "not added" in str(e)
else:
    raise SystemExit("FAIL: _validate_migration_statement accepted pre-existing column UPDATE")

# --- 2. phase='expand' rejects non-additive DDL (pre-DB ValueError) ---
#     These DDL verbs pass the general execute_migration verb allowlist but
#     are rejected by the additive phase guard. (DELETE is rejected even
#     earlier by the general allowlist, so it is not asserted here. UPDATE
#     backfills are covered in sections 1b/4b.)
for bad in [
    "DROP TABLE nope_xyz",
    "TRUNCATE TABLE nope_xyz",
    "ALTER TABLE nope_xyz DROP COLUMN c",
    "ALTER TABLE nope_xyz ALTER COLUMN c SET NOT NULL",
    "ALTER TABLE nope_xyz RENAME TO renamed",
    "ALTER TABLE nope_xyz SET TABLESPACE fast",
]:
    try:
        execute_migration(bad, phase="expand")
    except ValueError as e:
        assert "additive" in str(e), f"unexpected ValueError: {e}"
    else:
        raise SystemExit(f"FAIL: expand guard did NOT reject: {bad!r}")

# --- 3. a non-additive batch wrapped in transaction framing is still rejected ---
try:
    execute_migration("BEGIN;\nDROP TABLE nope_xyz;\nCOMMIT;", phase="expand")
except ValueError as e:
    assert "DROP" in str(e), f"unexpected ValueError: {e}"
else:
    raise SystemExit("FAIL: expand guard did NOT reject framed DROP batch")

# --- 4. phase='expand' ACCEPTS additive batches ---
#     They pass the guard and reach the mocked _conn (RuntimeError), not an
#     'additive' ValueError — proving the guard did not reject them.
for good in [
    "CREATE TABLE ok_xyz (id int)",
    "INSERT INTO ok_xyz (id) SELECT id FROM nope_xyz",
    "ALTER TABLE nope_xyz ADD COLUMN newcol int",
    "ALTER TABLE nope_xyz ADD CONSTRAINT ck CHECK (newcol > 0)",
    "UPDATE alembic_version SET version_num='0002'",
    (
        "ALTER TABLE users ADD COLUMN id_uuid uuid;\n"
        "UPDATE users SET id_uuid = gen_random_uuid();\n"
        "UPDATE alembic_version SET version_num='0002';"
    ),
]:
    try:
        execute_migration(good, phase="expand")
    except RuntimeError as e:
        assert "mock-no-db" in str(e)
    except ValueError as e:
        if "additive" in str(e):
            raise SystemExit(
                f"FAIL: additive batch wrongly rejected by expand guard: {good!r}"
            )
# --- 4b. UPDATE backfill of a column NOT added by the batch is rejected ---
for bad_batch in [
    "ALTER TABLE users ADD COLUMN id_uuid uuid;\nUPDATE users SET email='x';",
    "UPDATE users SET id_uuid = gen_random_uuid();",  # no ADD COLUMN at all
    "UPDATE users SET id_uuid = 1;\nUPDATE users SET id_uuid = 1, email='x';",
]:
    try:
        execute_migration(bad_batch, phase="expand")
    except ValueError as e:
        assert "not added" in str(e), f"unexpected ValueError: {e}"
    else:
        raise SystemExit(f"FAIL: expand guard accepted bad backfill batch: {bad_batch!r}")

# --- 5. phase=None SKIPS the guard entirely ---
#     A contractive verb reaches the mocked _conn (RuntimeError), proving the
#     expand guard did not fire when phase is not 'expand'.
try:
    execute_migration("DROP TABLE nope_xyz", phase=None)
except RuntimeError as e:
    assert "mock-no-db" in str(e)
except ValueError as e:
    if "additive" in str(e):
        raise SystemExit("FAIL: expand guard fired for phase=None")

# --- 6. invalid phase values are rejected BEFORE any DB access ---
#     Fail-closed: only None (full) and 'expand' are valid. A misspelled,
#     differently-cased, or 'contract' value must raise ValueError (invalid
#     phase) and NOT reach the mocked _conn (no RuntimeError), so a typo can
#     never silently bypass the expand guard.
for bad_phase in ["expend", "Expand", "EXPAND", "contract", "full", "", " "]:
    try:
        execute_migration("DROP TABLE nope_xyz", phase=bad_phase)
    except ValueError as e:
        assert "invalid phase" in str(e), f"unexpected ValueError: {e}"
    else:
        raise SystemExit(f"FAIL: invalid phase {bad_phase!r} ran unrestricted")

print("expand-phase verb guard: OK")
