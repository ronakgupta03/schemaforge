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


# --- 1. guard regex: contractive verbs match, additive verbs don't ---
assert _CONTRACTIVE_VERB.match("DROP TABLE users")
assert _CONTRACTIVE_VERB.match("ALTER TABLE users DROP COLUMN address")
assert _CONTRACTIVE_VERB.match("TRUNCATE TABLE users")
assert not _CONTRACTIVE_VERB.match("CREATE TABLE user_profiles (id int)")
assert not _CONTRACTIVE_VERB.match("INSERT INTO user_profiles (a) SELECT a FROM users")
assert not _CONTRACTIVE_VERB.match("UPDATE alembic_version SET version_num='0002'")

# --- 2. phase='expand' rejects contractive verbs (pre-DB ValueError) ---
for bad in [
    "DROP TABLE nope_xyz",
    "ALTER TABLE users DROP COLUMN address",
    "TRUNCATE TABLE nope_xyz",
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

# --- 4. phase='expand' ACCEPTS additive batches (CREATE + INSERT) ---
#     They pass the guard and reach the mocked _conn (RuntimeError), not an
#     'additive' ValueError — proving the guard did not reject them.
try:
    execute_migration(
        "CREATE TABLE t (id int);\nINSERT INTO t SELECT 1;", phase="expand"
    )
except RuntimeError as e:
    assert "mock-no-db" in str(e)
except ValueError as e:
    if "additive" in str(e):
        raise SystemExit("FAIL: additive batch wrongly rejected by expand guard")

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

print("expand-phase verb guard: OK")
