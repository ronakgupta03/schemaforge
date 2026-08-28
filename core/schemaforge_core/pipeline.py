"""SchemaForge deterministic pipeline CLI.

Commands:
  snapshot  --dsn URL --out out/db.json
  facts     --app demo-app --out out/code.json
  graph     --db out/db.json --code out/code.json --out out/graph.json --mermaid out/graph.mmd
  verify    --dir demo-app --dsn URL --baseline out/db_before.json
            [--parity-sql reference/post-split/parity.sql]
            [--queries demo-app/queries/bench.sql]
            [--explain-before out/explain_before.json]
            --out out/report.md
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .code_facts import collect_facts
from .db_snapshot import connect, diff_tables, snapshot
from .impact_graph import build, impacted_by, to_mermaid
from .models import CodeFacts, DBSnapshot
from .report import render_json, render_report


def cmd_snapshot(args: argparse.Namespace) -> None:
    with connect(args.dsn) as conn:
        snap = snapshot(conn)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(snap.to_dict(), indent=2))
    print(f"snapshot -> {args.out} ({len(snap.tables)} tables)")


def cmd_facts(args: argparse.Namespace) -> None:
    facts = collect_facts(args.app)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(facts.to_dict(), indent=2))
    print(
        f"facts -> {args.out} ({len(facts.models)} models, "
        f"{len(facts.endpoints)} endpoints, {len(facts.attr_accesses)} attr accesses, "
        f"{len(facts.raw_sql)} raw-sql refs)"
    )


def cmd_graph(args: argparse.Namespace) -> None:
    snap = DBSnapshot.from_dict(json.loads(Path(args.db).read_text()))
    facts = CodeFacts.from_dict(json.loads(Path(args.code).read_text()))
    g = build(snap, facts)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(g.to_dict(), indent=2))
    if args.mermaid:
        Path(args.mermaid).write_text(to_mermaid(g))
        print(f"graph -> {out} + {args.mermaid} ({len(g.nodes)} nodes, {len(g.edges)} edges)")
    else:
        print(f"graph -> {out} ({len(g.nodes)} nodes, {len(g.edges)} edges)")


def cmd_impact(args: argparse.Namespace) -> None:
    g = _load_graph(args.db, args.code)
    hit = impacted_by(g, [t.strip() for t in args.tables.split(",") if t.strip()])
    out = Path(args.out) if args.out else None
    text = json.dumps(hit, indent=2)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    print(text)


def _load_graph(db_path: str, code_path: str):
    snap = DBSnapshot.from_dict(json.loads(Path(db_path).read_text()))
    facts = CodeFacts.from_dict(json.loads(Path(code_path).read_text()))
    return build(snap, facts)


def _run(cmd: list[str], cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=900)


def _tool(name: str) -> str:
    """Resolve a console script next to the running interpreter, falling back to PATH.

    verify() shells out to alembic/pytest, which live in the same venv as the
    pipeline but are not guaranteed to be on PATH (e.g. sandbox agents with a
    minimal environment, or .vevn/bin/python invoked directly).
    """
    cand = Path(sys.executable).parent / name
    return str(cand) if cand.is_file() else name


def _test_dsn(dsn: str) -> str:
    """Append '_test' to the database name: .../bookstore -> .../bookstore_test.

    Query/fragment suffixes survive: .../bookstore?application_name=verify
    -> .../bookstore_test?application_name=verify.
    """
    p = urlsplit(dsn)
    path = p.path.rsplit("/", 1)
    path[-1] = f"{path[-1]}_test"
    return urlunsplit((p.scheme, p.netloc, "/".join(path), p.query, p.fragment))


def cmd_verify(args: argparse.Namespace) -> None:
    env = {**os.environ, "DATABASE_URL": args.dsn}
    # The app's tests force a separate test database; derive it from the DSN
    # so the sandbox flow needs no extra env (conftest's :5434 default only
    # matches the local host setup).
    env.setdefault("TEST_DATABASE_URL", _test_dsn(args.dsn))
    dir_ = Path(args.dir)

    alembic = _run([_tool("alembic"), "upgrade", "head"], dir_, env)

    with connect(args.dsn) as conn:
        after = snapshot(conn)
        before = DBSnapshot.from_dict(json.loads(Path(args.baseline).read_text()))
        diff = diff_tables(before, after)
        parity_ok: bool | None = None
        parity_out = ""
        if args.parity_sql:
            sql = Path(args.parity_sql).read_text()
            rows = conn.execute(sql).fetchall()
            parity_out = "\n".join(json.dumps(dict(r), default=str) for r in rows)
            parity_ok = all(
                bool(v)
                for r in rows
                for v in r.values()
                if isinstance(v, bool)
            )

    pytest = _run([_tool("pytest"), "-q"], dir_, env)

    before_explain: dict[str, float] = {}
    if args.explain_before and Path(args.explain_before).exists():
        before_explain = json.loads(Path(args.explain_before).read_text())
    explain: list[dict] = []
    for name, sql in _load_queries(Path(args.queries)):
        with connect(args.dsn) as conn:
            t0 = time.perf_counter()
            conn.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}")
            ms = (time.perf_counter() - t0) * 1000
        explain.append(
            {"query": name, "ms": round(ms, 1), "ms_before": before_explain.get(name)}
        )

    result = {
        "alembic_ok": alembic.returncode == 0,
        "alembic_output": (alembic.stdout + alembic.stderr)[-2000:],
        "pytest_ok": pytest.returncode == 0,
        "pytest_output": (pytest.stdout + pytest.stderr)[-3000:],
        "parity_ok": parity_ok,
        "parity_output": parity_out[-2000:],
        "diff": diff,
        "explain": explain,
    }
    report = render_report(result)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    (out.parent / "verify.json").write_text(
        json.dumps(render_json(result), indent=2) + "\n"
    )
    print(report)
    sys.exit(
        0 if (result["alembic_ok"] and result["pytest_ok"] and parity_ok is not False) else 1
    )


def cmd_bench(args: argparse.Namespace) -> None:
    """Record EXPLAIN ANALYZE timings (pre-migration baseline)."""
    timings: dict[str, float] = {}
    with connect(args.dsn) as conn:
        for name, sql in _load_queries(Path(args.queries)):
            t0 = time.perf_counter()
            conn.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}")
            timings[name] = round((time.perf_counter() - t0) * 1000, 1)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(timings, indent=2))
    print(json.dumps(timings, indent=2))


def _load_queries(path: Path) -> list[tuple[str, str]]:
    queries: list[tuple[str, str]] = []
    current: str | None = None
    buf: list[str] = []
    for line in path.read_text().splitlines():
        if line.startswith("-- name:"):
            if current:
                queries.append((current, "\n".join(buf).strip()))
            current = line.split(":", 1)[1].strip()
            buf = []
        else:
            buf.append(line)
    if current:
        queries.append((current, "\n".join(buf).strip()))
    return queries


def main() -> None:
    p = argparse.ArgumentParser(prog="schemaforge_core")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot")
    s.add_argument("--dsn", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_snapshot)

    s = sub.add_parser("facts")
    s.add_argument("--app", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_facts)

    s = sub.add_parser("graph")
    s.add_argument("--db", required=True)
    s.add_argument("--code", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--mermaid")
    s.set_defaults(fn=cmd_graph)

    s = sub.add_parser("impact")
    s.add_argument("--db", required=True)
    s.add_argument("--code", required=True)
    s.add_argument("--tables", required=True, help="comma-separated table names")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_impact)

    s = sub.add_parser("verify")
    s.add_argument("--dir", required=True)
    s.add_argument("--dsn", required=True)
    s.add_argument("--baseline", required=True)
    s.add_argument("--parity-sql")
    s.add_argument("--queries", required=True)
    s.add_argument("--explain-before")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("bench")
    s.add_argument("--dsn", required=True)
    s.add_argument("--queries", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_bench)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
