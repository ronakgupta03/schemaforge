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
