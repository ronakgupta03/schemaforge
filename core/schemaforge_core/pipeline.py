"""SchemaForge deterministic pipeline CLI.

Commands:
  snapshot  --dsn URL --out out/db.json
  facts     --app <app-dir> --out out/code.json
  graph     --db out/db.json --code out/code.json --out out/graph.json --mermaid out/graph.mmd
  verify    --dir <app-dir> --dsn URL --baseline out/db_before.json
            [--parity-sql <parity.sql>]
            [--queries <queries.sql>]
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
from .code_facts_ts import collect_facts_ts
from .detect import detect_language, detect_migration_tool
from .db_snapshot import connect, diff_tables, snapshot
from .impact_graph import build, impacted_by, impacted_by_columns, to_mermaid
from .models import CodeFacts, DBSnapshot
from .report import render_json, render_report


def cmd_snapshot(args: argparse.Namespace) -> None:
    with connect(args.dsn) as conn:
        snap = snapshot(conn)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(snap.to_dict(), indent=2))
    print(f"snapshot -> {args.out} ({len(snap.tables)} tables)")


def cmd_facts(args: argparse.Namespace) -> None:
    lang = getattr(args, "lang", "auto") or "auto"
    if lang == "auto":
        lang = detect_language(args.app)
    facts = collect_facts_ts(args.app) if lang == "ts" else collect_facts(args.app)
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



def cmd_validate_phase(args: argparse.Namespace) -> None:
    if Path(args.migration).suffix == ".sql":
        from .migration_sql import validate_phase_sql
        validate_fn = validate_phase_sql
    else:
        from .migration import validate_phase
        validate_fn = validate_phase
    try:
        validate_fn(args.migration, args.phase)
        print(f"validate-phase -> OK ({args.phase}-pure)")
    except ValueError as exc:
        print(f"validate-phase -> FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)


def cmd_contract_gate(args: argparse.Namespace) -> None:
    g = _load_graph(args.db, args.code)
    columns = [c.strip() for c in args.columns.split(",") if c.strip()]
    result = impacted_by_columns(g, columns)
    text = json.dumps(result, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    verdict = "SAFE" if result["safe"] else "BLOCKED"
    print(f"contract-gate -> {verdict} ({len(result['blockers'])} blocker(s))")
    if not result["safe"]:
        for b in result["blockers"]:
            print(f"  [{b['kind']}] {b['file']}:{b['label']}")


def cmd_analyze_locks(args: argparse.Namespace) -> None:
    if Path(args.migration).suffix == ".sql":
        from .migration_sql import analyze_locks_sql
        reports = analyze_locks_sql(args.migration)
    else:
        from .migration import analyze_locks
        reports = analyze_locks(args.migration)
    data = [{"statement": r.statement, "line": r.lineno, "lock": r.lock,
             "rewrites": r.rewrites, "risk": r.risk, "alternative": r.alternative}
            for r in reports]
    text = json.dumps(data, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    for r in reports:
        flag = "!" if r.risk == "dangerous" else ("." if r.risk == "brief-lock" else " ")
        print(f"{flag} L{r.lineno} [{r.lock}] {r.risk}: {r.statement[:70]}")
        if r.alternative:
            print(f"      -> {r.alternative}")

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
    """Append '_test' to the database name: .../appdb -> .../appdb_test.

    Query/fragment suffixes survive: .../appdb?application_name=verify
    -> .../appdb_test?application_name=verify.
    """
    p = urlsplit(dsn)
    path = p.path.rsplit("/", 1)
    path[-1] = f"{path[-1]}_test"
    return urlunsplit((p.scheme, p.netloc, "/".join(path), p.query, p.fragment))


def _apply_sql_migrations(dir_: Path, args: argparse.Namespace, env: dict) -> tuple[bool, str]:
    """Apply raw-SQL migrations in lexicographic order (or a single --migration)."""
    if getattr(args, "migration", None):
        sqls = [Path(args.migration)]
    else:
        mdir = dir_ / "migrations"
        sqls = sorted(mdir.glob("*.sql")) if mdir.is_dir() else []
    ok, out = True, ""
    for sf in sqls:
        r = _run(["psql", "-v", "ON_ERROR_STOP=1", "-f", str(sf), args.dsn], dir_, env)
        ok = ok and r.returncode == 0
        out += (r.stdout + r.stderr)[-2000:]
    return ok, out


def _run_ts_tests(dir_: Path, env: dict) -> tuple[bool, str]:
    """Run `npm test` if package.json defines a test script; else data parity is
    the sole invariant (TypeScript apps have no pytest)."""
    pkg = dir_ / "package.json"
    if pkg.exists():
        try:
            scripts = json.loads(pkg.read_text()).get("scripts", {})
        except (OSError, ValueError):
            scripts = {}
        if scripts.get("test"):
            r = _run(["npm", "test", "--silent"], dir_, env)
            return r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    return True, "(no test script; data parity is the sole invariant)"


def cmd_verify(args: argparse.Namespace) -> None:
    env = {**os.environ, "DATABASE_URL": args.dsn}
    # The app's tests force a separate test database; derive it from the DSN
    # so the sandbox flow needs no extra env (conftest's :5434 default only
    # matches the local host setup).
    env.setdefault("TEST_DATABASE_URL", _test_dsn(args.dsn))
    dir_ = Path(args.dir)

    tool = args.tool if args.tool != "auto" else detect_migration_tool(str(dir_))

    # --- apply the migration ---
    if tool == "sql":
        apply_ok, apply_out = _apply_sql_migrations(dir_, args, env)
    else:  # alembic (default)
        alembic = _run([_tool("alembic"), "upgrade", "head"], dir_, env)
        apply_ok = alembic.returncode == 0
        apply_out = (alembic.stdout + alembic.stderr)[-2000:]

    # --- schema diff + data parity (language-agnostic) ---
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

    # --- contract tests ---
    if tool == "sql":
        test_ok, test_out = _run_ts_tests(dir_, env)
    else:
        res = _run([_tool("pytest"), "-q"], dir_, env)
        test_ok = res.returncode == 0
        test_out = (res.stdout + res.stderr)[-3000:]

    # --- query plans (language-agnostic) ---
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
        "tool": "sql" if tool == "sql" else "alembic",
        "apply_ok": apply_ok,
        "apply_output": apply_out,
        "test_ok": test_ok,
        "test_output": test_out,
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
    sys.exit(0 if (apply_ok and test_ok and parity_ok is not False) else 1)


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
    s.add_argument("--lang", choices=["auto", "python", "ts"], default="auto")
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

    s = sub.add_parser("validate-phase")
    s.add_argument("--migration", required=True)
    s.add_argument("--phase", required=True, choices=["expand", "contract"])
    s.set_defaults(fn=cmd_validate_phase)

    s = sub.add_parser("contract-gate")
    s.add_argument("--db", required=True)
    s.add_argument("--code", required=True)
    s.add_argument("--columns", required=True, help="comma-separated table.column names")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_contract_gate)

    s = sub.add_parser("analyze-locks")
    s.add_argument("--migration", required=True)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_analyze_locks)

    s = sub.add_parser("verify")
    s.add_argument("--dir", required=True)
    s.add_argument("--dsn", required=True)
    s.add_argument("--baseline", required=True)
    s.add_argument("--parity-sql")
    s.add_argument("--queries", required=True)
    s.add_argument("--explain-before")
    s.add_argument("--out", required=True)
    s.add_argument("--tool", choices=["auto", "alembic", "sql"], default="auto")
    s.add_argument("--migration", help="single SQL migration file (tool=sql)")
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
