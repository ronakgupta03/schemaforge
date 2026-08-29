"""Functional test: execute_migration(phase='expand') rejects contractive verbs.

The expand guard runs in the statement-validation loop BEFORE any database
connection, so these assertions need no live DB and no running MCP server.
_conn is monkeypatched so additive batches (which pass the guard and would
otherwise reach the DB) hit a mock instead.

Run: .vevn/bin/python mcp-servers/postgres-mcp/test_phase.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import server  # noqa: E402
from server import execute_migration, _CONTRACTIVE_VERB  # noqa: E402


class _MockConn:
    """Stand-in for _conn: additive batches that pass the guard reach here."""

    def __init__(self, *args, **kwargs):
        raise RuntimeError("mock-no-db")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


server._conn = _MockConn  # hermetic: never touch a real DB


# --- 1. guard regex: contractive matches, additive does not ---
# Contractive (rejected in expand):
assert _CONTRACTIVE_VERB.match("DROP TABLE users")
assert _CONTRACTIVE_VERB.match("DROP INDEX users_email")
assert _CONTRACTIVE_VERB.match("ALTER TABLE users DROP COLUMN address")
assert _CONTRACTIVE_VERB.match("TRUNCATE TABLE users")
assert _CONTRACTIVE_VERB.match("ALTER TABLE users ALTER COLUMN address SET NOT NULL")
assert _CONTRACTIVE_VERB.match("ALTER TABLE users ALTER COLUMN address TYPE bigint")
# Additive (allowed in expand): CREATE, INSERT, UPDATE alembic_version, ADD COLUMN,
# ADD CONSTRAINT, SET DEFAULT — none of these remove or rewrite existing schema.
assert not _CONTRACTIVE_VERB.match("CREATE TABLE user_profiles (id int)")
assert not _CONTRACTIVE_VERB.match("CREATE INDEX CONCURRENTLY ix_users_email ON users(email)")
assert not _CONTRACTIVE_VERB.match("INSERT INTO user_profiles (a) SELECT a FROM users")
assert not _CONTRACTIVE_VERB.match("UPDATE alembic_version SET version_num='0002'")
assert not _CONTRACTIVE_VERB.match("ALTER TABLE users ADD COLUMN x int")
assert not _CONTRACTIVE_VERB.match(
    "ALTER TABLE users ADD COLUMN x int NOT NULL DEFAULT 0"
)
assert not _CONTRACTIVE_VERB.match("ALTER TABLE users ADD CONSTRAINT chk CHECK (x > 0)")
assert not _CONTRACTIVE_VERB.match("ALTER TABLE users ALTER COLUMN address SET DEFAULT ''")
# multi-line additive statement (regex must span newlines for the ALTER clause)
assert not _CONTRACTIVE_VERB.match("ALTER TABLE users\n  ADD COLUMN x int")

# --- 2. phase='expand' rejects contractive verbs (pre-DB ValueError) ---
for bad in [
    "DROP TABLE nope_xyz",
    "ALTER TABLE users DROP COLUMN address",
    "TRUNCATE TABLE nope_xyz",
    "ALTER TABLE users ALTER COLUMN address SET NOT NULL",
]:
    try:
        execute_migration(bad, phase="expand")
    except ValueError as e:
        assert "additive" in str(e), f"unexpected ValueError: {e}"
    else:
        raise SystemExit(f"FAIL: expand guard did NOT reject: {bad!r}")

# --- 3. a contractive batch wrapped in transaction framing is still rejected ---
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
    "CREATE TABLE t (id int);\nINSERT INTO t SELECT 1;",
    "ALTER TABLE users ADD COLUMN x int",  # additive ALTER must be allowed
    "ALTER TABLE users ADD CONSTRAINT chk CHECK (x > 0)",
]:
    try:
        execute_migration(good, phase="expand")
    except RuntimeError as e:
        assert "mock-no-db" in str(e)
    except ValueError as e:
        if "additive" in str(e):
            raise SystemExit(f"FAIL: additive batch wrongly rejected by expand guard: {good!r}")

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
        assert "invalid phase" in str(e), f"unexpected ValueError for {bad_phase!r}: {e}"
    except RuntimeError:
        raise SystemExit(f"FAIL: invalid phase {bad_phase!r} bypassed the guard (reached DB)")
    else:
        raise SystemExit(f"FAIL: invalid phase {bad_phase!r} ran unrestricted")

print("expand-phase verb guard: OK")
