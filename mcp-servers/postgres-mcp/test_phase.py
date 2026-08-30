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
    _update_set_columns,
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

# --- 1e. UPDATE..FROM join-form backfills (target alias) ---
# The live UUIDv7 expand migration backfills FK twins as
# `UPDATE comments c SET blog_id_uuid = b.uuid FROM blogs b WHERE ...` — the
# target alias between table and SET must parse (previously rejected with
# "statement not allowed by execute_migration").
assert _update_set_columns(
    "UPDATE comments c SET blog_id_uuid = b.uuid FROM blogs b "
    "WHERE b.id = c.blog_id AND c.blog_id_uuid IS NULL"
) == ("comments", ["blog_id_uuid"])
assert _update_set_columns(
    "UPDATE blog_votes bv SET blog_id_uuid = b.uuid, user_id_uuid = u.uuid "
    "FROM users u WHERE u.id = bv.user_id AND bv.user_id_uuid IS NULL"
) == ("blog_votes", ["blog_id_uuid", "user_id_uuid"])
assert _update_set_columns(
    "UPDATE comment_votes cv SET comment_id_uuid = c.uuid, user_id_uuid = u.uuid "
    "FROM comments c WHERE c.id = cv.comment_id AND cv.comment_id_uuid IS NULL"
) == ("comment_votes", ["comment_id_uuid", "user_id_uuid"])
assert _update_set_columns(
    "UPDATE refresh_tokens rt SET user_id_uuid = u.uuid FROM users u "
    "WHERE u.id = rt.user_id AND rt.user_id_uuid IS NULL"
) == ("refresh_tokens", ["user_id_uuid"])
# scalar form (no alias) and schema-qualified/aliased variants still parse:
assert _update_set_columns("UPDATE users SET uuid = 1 WHERE uuid IS NULL") == (
    "users",
    ["uuid"],
)
assert _update_set_columns("UPDATE public.users u SET uuid = 1") == (
    "public.users",
    ["uuid"],
)
# alias form stays bounded: SET on a pre-existing column is rejected
assert _is_expand_allowed(
    "UPDATE comments c SET blog_id = b.id FROM blogs b WHERE b.id = c.blog_id",
    {"comments": {"blog_id_uuid"}},
) is not None
# alias form without batch context is rejected (fail-closed)
assert _is_expand_allowed(
    "UPDATE comments c SET blog_id_uuid = b.uuid FROM blogs b WHERE b.id = c.blog_id",
    None,
) is not None

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

# --- 4c. the live UUIDv7 expand batch (alias + FROM join form) passes ---
# Mirrors backend/migrations/2025-08-30_uuidv7_expand.sql minus the already-
# applied sf_uuidv7() function: ADD uuid x9, backfill uuid x9, ADD FK twins
# x11, UPDATE..FROM twin backfills x11, unique index x9, index twins x6,
# SET DEFAULT x9. Every SET column is ADDed by this batch, so each statement
# must pass _validate_migration_statement AND the expand allowlist, and the
# whole batch must reach the mocked _conn.
_UUIDV7_BATCH = [
    "ALTER TABLE users ADD COLUMN uuid uuid;",
    "ALTER TABLE blogs ADD COLUMN uuid uuid;",
    "ALTER TABLE comments ADD COLUMN uuid uuid;",
    "ALTER TABLE blog_votes ADD COLUMN uuid uuid;",
    "ALTER TABLE comment_votes ADD COLUMN uuid uuid;",
    "ALTER TABLE otps ADD COLUMN uuid uuid;",
    "ALTER TABLE refresh_tokens ADD COLUMN uuid uuid;",
    "ALTER TABLE blog_reactions ADD COLUMN uuid uuid;",
    "ALTER TABLE glossary_terms ADD COLUMN uuid uuid;",
    "UPDATE users SET uuid = sf_uuidv7((EXTRACT(EPOCH FROM COALESCE(created_at, clock_timestamp())) * 1000)::bigint) WHERE uuid IS NULL;",
    "UPDATE blogs SET uuid = sf_uuidv7((EXTRACT(EPOCH FROM COALESCE(created_at, clock_timestamp())) * 1000)::bigint) WHERE uuid IS NULL;",
    "UPDATE comments SET uuid = sf_uuidv7((EXTRACT(EPOCH FROM COALESCE(created_at, clock_timestamp())) * 1000)::bigint) WHERE uuid IS NULL;",
    "UPDATE blog_votes SET uuid = sf_uuidv7((EXTRACT(EPOCH FROM COALESCE(created_at, clock_timestamp())) * 1000)::bigint) WHERE uuid IS NULL;",
    "UPDATE comment_votes SET uuid = sf_uuidv7((EXTRACT(EPOCH FROM COALESCE(created_at, clock_timestamp())) * 1000)::bigint) WHERE uuid IS NULL;",
    "UPDATE otps SET uuid = sf_uuidv7((EXTRACT(EPOCH FROM COALESCE(created_at, clock_timestamp())) * 1000)::bigint) WHERE uuid IS NULL;",
    "UPDATE refresh_tokens SET uuid = sf_uuidv7((EXTRACT(EPOCH FROM COALESCE(created_at, clock_timestamp())) * 1000)::bigint) WHERE uuid IS NULL;",
    "UPDATE blog_reactions SET uuid = sf_uuidv7((EXTRACT(EPOCH FROM COALESCE(created_at, clock_timestamp())) * 1000)::bigint) WHERE uuid IS NULL;",
    "UPDATE glossary_terms SET uuid = sf_uuidv7((EXTRACT(EPOCH FROM COALESCE(created_at, clock_timestamp())) * 1000)::bigint) WHERE uuid IS NULL;",
    "ALTER TABLE comments ADD COLUMN blog_id_uuid uuid;",
    "ALTER TABLE comments ADD COLUMN user_id_uuid uuid;",
    "ALTER TABLE comments ADD COLUMN parent_id_uuid uuid;",
    "ALTER TABLE blog_votes ADD COLUMN blog_id_uuid uuid;",
    "ALTER TABLE blog_votes ADD COLUMN user_id_uuid uuid;",
    "ALTER TABLE comment_votes ADD COLUMN comment_id_uuid uuid;",
    "ALTER TABLE comment_votes ADD COLUMN user_id_uuid uuid;",
    "ALTER TABLE refresh_tokens ADD COLUMN user_id_uuid uuid;",
    "ALTER TABLE blog_reactions ADD COLUMN blog_id_uuid uuid;",
    "ALTER TABLE blog_reactions ADD COLUMN user_id_uuid uuid;",
    "ALTER TABLE glossary_terms ADD COLUMN blog_id_uuid uuid;",
    "UPDATE comments c SET blog_id_uuid = b.uuid FROM blogs b WHERE b.id = c.blog_id AND c.blog_id_uuid IS NULL;",
    "UPDATE comments c SET user_id_uuid = u.uuid FROM users u WHERE u.id = c.user_id AND c.user_id_uuid IS NULL;",
    "UPDATE comments c SET parent_id_uuid = p.uuid FROM comments p WHERE p.id = c.parent_id AND c.parent_id_uuid IS NULL;",
    "UPDATE blog_votes bv SET blog_id_uuid = b.uuid FROM blogs b WHERE b.id = bv.blog_id AND bv.blog_id_uuid IS NULL;",
    "UPDATE blog_votes bv SET user_id_uuid = u.uuid FROM users u WHERE u.id = bv.user_id AND bv.user_id_uuid IS NULL;",
    "UPDATE comment_votes cv SET comment_id_uuid = c.uuid FROM comments c WHERE c.id = cv.comment_id AND cv.comment_id_uuid IS NULL;",
    "UPDATE comment_votes cv SET user_id_uuid = u.uuid FROM users u WHERE u.id = cv.user_id AND cv.user_id_uuid IS NULL;",
    "UPDATE refresh_tokens rt SET user_id_uuid = u.uuid FROM users u WHERE u.id = rt.user_id AND rt.user_id_uuid IS NULL;",
    "UPDATE blog_reactions br SET blog_id_uuid = b.uuid FROM blogs b WHERE b.id = br.blog_id AND br.blog_id_uuid IS NULL;",
    "UPDATE blog_reactions br SET user_id_uuid = u.uuid FROM users u WHERE u.id = br.user_id AND br.user_id_uuid IS NULL;",
    "UPDATE glossary_terms gt SET blog_id_uuid = b.uuid FROM blogs b WHERE b.id = gt.blog_id AND gt.blog_id_uuid IS NULL;",
    "CREATE UNIQUE INDEX users_uuid_key ON users (uuid);",
    "CREATE UNIQUE INDEX blogs_uuid_key ON blogs (uuid);",
    "CREATE UNIQUE INDEX comments_uuid_key ON comments (uuid);",
    "CREATE UNIQUE INDEX blog_votes_uuid_key ON blog_votes (uuid);",
    "CREATE UNIQUE INDEX comment_votes_uuid_key ON comment_votes (uuid);",
    "CREATE UNIQUE INDEX otps_uuid_key ON otps (uuid);",
    "CREATE UNIQUE INDEX refresh_tokens_uuid_key ON refresh_tokens (uuid);",
    "CREATE UNIQUE INDEX blog_reactions_uuid_key ON blog_reactions (uuid);",
    "CREATE UNIQUE INDEX glossary_terms_uuid_key ON glossary_terms (uuid);",
    "CREATE UNIQUE INDEX blog_votes_blog_id_uuid_user_id_uuid_key ON blog_votes (blog_id_uuid, user_id_uuid);",
    "CREATE INDEX idx_blog_votes_blog_uuid ON blog_votes (blog_id_uuid);",
    "CREATE INDEX idx_blog_votes_user_uuid ON blog_votes (user_id_uuid);",
    "CREATE UNIQUE INDEX comment_votes_comment_id_uuid_user_id_uuid_key ON comment_votes (comment_id_uuid, user_id_uuid);",
    "CREATE UNIQUE INDEX blog_reactions_blog_id_uuid_user_id_uuid_reaction_type_key ON blog_reactions (blog_id_uuid, user_id_uuid, reaction_type);",
    "CREATE UNIQUE INDEX glossary_terms_blog_id_uuid_term_key ON glossary_terms (blog_id_uuid, term);",
    "ALTER TABLE users ALTER COLUMN uuid SET DEFAULT sf_uuidv7();",
    "ALTER TABLE blogs ALTER COLUMN uuid SET DEFAULT sf_uuidv7();",
    "ALTER TABLE comments ALTER COLUMN uuid SET DEFAULT sf_uuidv7();",
    "ALTER TABLE blog_votes ALTER COLUMN uuid SET DEFAULT sf_uuidv7();",
    "ALTER TABLE comment_votes ALTER COLUMN uuid SET DEFAULT sf_uuidv7();",
    "ALTER TABLE otps ALTER COLUMN uuid SET DEFAULT sf_uuidv7();",
    "ALTER TABLE refresh_tokens ALTER COLUMN uuid SET DEFAULT sf_uuidv7();",
    "ALTER TABLE blog_reactions ALTER COLUMN uuid SET DEFAULT sf_uuidv7();",
    "ALTER TABLE glossary_terms ALTER COLUMN uuid SET DEFAULT sf_uuidv7();",
]
_uuidv7_added = _added_columns(_UUIDV7_BATCH)
for _stmt in _UUIDV7_BATCH:
    _validate_migration_statement(_stmt, _uuidv7_added)
    assert _is_expand_allowed(_stmt, _uuidv7_added) is None, _stmt
try:
    execute_migration("\n".join(_UUIDV7_BATCH), phase="expand")
except RuntimeError as e:
    assert "mock-no-db" in str(e)
except ValueError as e:
    raise SystemExit(f"FAIL: live UUIDv7 expand batch rejected: {e}")

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
