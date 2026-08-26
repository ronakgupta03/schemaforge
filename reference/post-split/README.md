# Golden post-split outcome (reference only)

The expected result of the `users -> users + user_profiles` split. NOT wired
into `demo-app/` — the agent authors its own migration at runtime. This
reference is used to (a) sanity-check the agent's output and (b) prove the
deterministic pipeline end-to-end.

| File | What it is |
|---|---|
| alembic/versions/0002_split_users.py | data-preserving expand/backfill/contract migration |
| app/models.py | post-split ORM models |
| app/routers/users.py | join-based API (response shape unchanged) |
| queries/bench.sql | post-split EXPLAIN ANALYZE queries (joined reports query) |
| parity.sql | data-preservation assertions run by `pipeline verify` |
| parity.sql | data-preservation assertions run by `pipeline verify` |