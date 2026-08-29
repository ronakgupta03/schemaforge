"""Pipeline dispatch tests: cmd_facts / validate-phase / analyze-locks / verify
route to the python or TS / SQL code paths by language / file extension."""
import argparse
import json
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from schemaforge_core import pipeline
from schemaforge_core.pipeline import main

FIX = Path(__file__).parent / "fixtures" / "ts_app"


def test_cmd_facts_dispatches_ts(tmp_path):
    out = tmp_path / "code.json"
    sys.argv = ["sf-pipeline", "facts", "--app", str(FIX), "--out", str(out)]
    main()
    data = json.loads(out.read_text())
    assert any(m["table"] == "posts" for m in data["models"])
    assert any(e["path"] == "/api/posts" for e in data["endpoints"])


def test_cmd_facts_lang_python_still_works(tmp_path):
    # the demo-app is python + sqlalchemy; explicit --lang python must still
    # route to the python extractor (no regression).
    demo = Path(__file__).parent.parent / "demo-app"
    out = tmp_path / "code.json"
    sys.argv = ["sf-pipeline", "facts", "--app", str(demo),
                "--out", str(out), "--lang", "python"]
    if demo.is_dir():
        main()
        data = json.loads(out.read_text())
        assert any(m["table"] == "users" for m in data["models"])


def test_validate_phase_dispatches_sql(tmp_path):
    p = tmp_path / "mig.sql"
    p.write_text("ALTER TABLE users DROP COLUMN address;\n")
    sys.argv = ["sf-pipeline", "validate-phase", "--migration", str(p),
                "--phase", "contract"]
    main()  # contract phase accepts the ALTER -> returns normally


def test_validate_phase_sql_rejected_in_expand(tmp_path):
    p = tmp_path / "mig.sql"
    p.write_text("ALTER TABLE users DROP COLUMN address;\n")
    sys.argv = ["sf-pipeline", "validate-phase", "--migration", str(p),
                "--phase", "expand"]
    with pytest.raises(SystemExit):
        main()  # expand rejects contract op -> SystemExit(1)


def test_analyze_locks_dispatches_sql(tmp_path):
    p = tmp_path / "mig.sql"
    p.write_text("CREATE TABLE t (id int);\nALTER TABLE t DROP COLUMN x;\n")
    out = tmp_path / "locks.json"
    sys.argv = ["sf-pipeline", "analyze-locks", "--migration", str(p),
                "--out", str(out)]
    main()
    data = json.loads(out.read_text())
    assert len(data) == 2
    assert data[0]["lock"] == "none"
    assert data[1]["lock"] == "AccessExclusive"


def test_verify_sql_path_applies_and_tests(monkeypatch, tmp_path):
    """The SQL verify path applies *.sql via psql and runs npm test (or skips),
    producing a PASS report without touching Alembic or pytest."""
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001.sql").write_text("CREATE TABLE t (id int);\n")
    (tmp_path / "baseline.json").write_text('{"tables": {}}')
    (tmp_path / "queries.sql").write_text("-- name: q\nSELECT 1;\n")
    out = tmp_path / "report.md"

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            return []  # EXPLAIN + parity return nothing we read

    monkeypatch.setattr(pipeline, "connect", lambda dsn: FakeConn())
    monkeypatch.setattr(pipeline, "snapshot", lambda conn: pipeline.DBSnapshot())
    monkeypatch.setattr(pipeline, "diff_tables", lambda a, b: {})
    monkeypatch.setattr(pipeline, "_run",
                        lambda cmd, cwd, env: CompletedProcess(cmd, 0, "", ""))

    args = argparse.Namespace(
        dir=str(tmp_path), dsn="postgresql://x@localhost/x",
        baseline=str(tmp_path / "baseline.json"), parity_sql=None,
        queries=str(tmp_path / "queries.sql"), explain_before=None,
        out=str(out), tool="sql", migration=None,
    )
    with pytest.raises(SystemExit) as exc:
        pipeline.cmd_verify(args)
    assert exc.value.code == 0
    assert out.exists()
    report = out.read_text()
    assert "PASS" in report
    assert "Alembic" not in report  # SQL path must not emit Alembic-specific prose


def test_apply_sql_orders_concurrent_with_txn(monkeypatch, tmp_path):
    """A CONCURRENTLY statement splits the run into ordered segments: the
    pending transactional segment is flushed before the concurrent statement,
    then a new segment begins after -- preserving order so a later statement
    can depend on a concurrently created index."""
    p = tmp_path / "mig.sql"
    p.write_text(
        "CREATE TABLE t (id int);\n"
        "CREATE INDEX CONCURRENTLY idx ON t (id);\n"
        "INSERT INTO t VALUES (1);\n"
    )
    calls = []

    def fake_run(cmd, cwd, env):
        calls.append(cmd)
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(pipeline, "_run", fake_run)
    args = argparse.Namespace(migration=str(p), dsn="postgresql://x@localhost/x")
    ok, out = pipeline._apply_sql_migrations(tmp_path, args, {})
    assert ok
    # call 1: txn segment [CREATE TABLE] via --single-transaction -f
    # call 2: concurrent CREATE INDEX via -c
    # call 3: txn segment [INSERT] via --single-transaction -f
    assert len(calls) == 3
    assert "--single-transaction" in calls[0] and "-f" in calls[0]
    assert "-c" in calls[1]
    assert "CONCURRENTLY" in calls[1][calls[1].index("-c") + 1]
    assert "--single-transaction" in calls[2] and "-f" in calls[2]


def test_apply_sql_stops_when_txn_segment_fails(monkeypatch, tmp_path):
    """A failing transactional segment stops the run; later statements
    (including a concurrent statement) are not applied."""
    p = tmp_path / "mig.sql"
    p.write_text("CREATE TABLE t (id int);\nCREATE INDEX CONCURRENTLY i ON t (id);\n")
    calls = []

    def fake_run(cmd, cwd, env):
        calls.append(cmd)
        return CompletedProcess(cmd, 1, "", "boom")

    monkeypatch.setattr(pipeline, "_run", fake_run)
    args = argparse.Namespace(migration=str(p), dsn="postgresql://x@localhost/x")
    ok, out = pipeline._apply_sql_migrations(tmp_path, args, {})
    assert not ok
    # only the failing transactional flush ran; the concurrent stmt never did
    assert len(calls) == 1
    assert "--single-transaction" in calls[0]


def test_apply_sql_stops_when_concurrent_stmt_fails(monkeypatch, tmp_path):
    """A failing CONCURRENTLY statement stops the run after flushing the
    pending transactional segment; later statements are not applied."""
    p = tmp_path / "mig.sql"
    p.write_text(
        "CREATE TABLE t (id int);\n"
        "CREATE INDEX CONCURRENTLY i ON t (id);\n"
        "INSERT INTO t VALUES (1);\n"
    )
    calls = []

    def fake_run(cmd, cwd, env):
        calls.append(cmd)
        # txn segment (call 1) succeeds; the concurrent statement (call 2) fails
        return CompletedProcess(cmd, 0 if len(calls) == 1 else 1, "", "boom")

    monkeypatch.setattr(pipeline, "_run", fake_run)
    args = argparse.Namespace(migration=str(p), dsn="postgresql://x@localhost/x")
    ok, out = pipeline._apply_sql_migrations(tmp_path, args, {})
    assert not ok
    # call 1 = txn flush (ok), call 2 = concurrent (fails); no third call
    assert len(calls) == 2
    assert "--single-transaction" in calls[0]
    assert "-c" in calls[1]


def test_apply_sql_concurrently_in_string_stays_transactional(monkeypatch, tmp_path):
    """A 'concurrently' inside a string literal or dollar-quoted body must NOT
    split the batch -- only an actual CREATE INDEX CONCURRENTLY statement runs
    outside the transaction; the rest stay in one transactional segment."""
    p = tmp_path / "mig.sql"
    p.write_text(
        "INSERT INTO logs VALUES ('CREATE INDEX CONCURRENTLY x');\n"
        "CREATE FUNCTION f() AS $$ CREATE INDEX CONCURRENTLY y $$ LANGUAGE sql;\n"
        "CREATE TABLE t (id int);\n"
    )
    calls = []

    def fake_run(cmd, cwd, env):
        calls.append(cmd)
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(pipeline, "_run", fake_run)
    args = argparse.Namespace(migration=str(p), dsn="postgresql://x@localhost/x")
    ok, out = pipeline._apply_sql_migrations(tmp_path, args, {})
    assert ok
    # no concurrent (-c) call fired; all 3 statements ran in one txn segment
    assert len(calls) == 1
    assert "--single-transaction" in calls[0]
    assert "-c" not in calls[0]
