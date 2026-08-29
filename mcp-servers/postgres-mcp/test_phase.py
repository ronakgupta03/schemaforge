"""Functional test: execute_migration(phase='expand') rejects non-additive verbs.

The expand guard is an ALLOWLIST, not a denylist: only additive statements
(CREATE, INSERT backfill, UPDATE alembic_version, ADD COLUMN/CONSTRAINT,
ALTER COLUMN SET DEFAULT, VALIDATE CONSTRAINT) pass; everything else is
rejected so a mis-authored expand fails safely rather than modifying
existing objects. This keeps the test hermetic: no real DB is touched.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import server  # noqa: E402
from server import execute_migration, _is_expand_allowed  # noqa: E402


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
assert _is_expand_allowed("ALTER TABLE users VALIDATE CONSTRAINT chk") is None
# multi-line additive statement (regex must span newlines for the ALTER clause)
assert _is_expand_allowed("ALTER TABLE users\n  ADD COLUMN x int") is None

# --- 2. phase='expand' rejects non-additive DDL (pre-DB ValueError) ---
#     These DDL verbs pass the general execute_migration verb allowlist but
#     are rejected by the additive phase guard. (DELETE/UPDATE are rejected
#     even earlier by the general allowlist, so they are not asserted here.)
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
