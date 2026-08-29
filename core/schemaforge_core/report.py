"""Safety report rendering (markdown, for chat display + PR body)."""
from __future__ import annotations

import datetime as _dt


def render_report(r: dict) -> str:
    tool = r.get("tool", "alembic")
    apply_label = "Alembic migration" if tool == "alembic" else "SQL migration apply"
    lines = ["# SchemaForge Safety Report", ""]
    lines.append(f"Generated: {_dt.datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("## Verification")
    lines.append(f"- {apply_label}: {'PASS' if r['apply_ok'] else 'FAIL'}")
    lines.append(f"- Application tests: {'PASS' if r['test_ok'] else 'FAIL'}")
    if r.get("parity_ok") is not None:
        lines.append(f"- Data parity: {'PASS' if r['parity_ok'] else 'FAIL'}")
    lines.append("")
    lines.append("## Schema diff")
    d = r.get("diff", {})
    for key in ("added_tables", "removed_tables", "added_columns", "removed_columns"):
        items = d.get(key, [])
        lines.append(f"- {key.replace('_', ' ')}: {', '.join(items) if items else '(none)'}")
    lines.append("")
    lines.append("## Query performance (sandbox, EXPLAIN ANALYZE, wall ms)")
    for e in r.get("explain", []):
        before = f"{e['ms_before']} ms" if e.get("ms_before") is not None else "n/a"
        lines.append(f"- `{e['query']}`: before = {before}, after = {e['ms']} ms")
    lines.append("")
    lines.append("## Rollback")
    if tool == "alembic":
        lines.append("`alembic downgrade -1` restores the previous schema "
                     "(the revision ships its own `downgrade()`).")
    else:
        lines.append("Each SQL migration ships a paired `down`/revert script applied "
                     "in reverse order to restore the previous schema.")
    lines.append("")
    lines.append("## Approval checklist")
    lines.append("- [ ] Impact graph reviewed")
    lines.append("- [ ] Schema diff reviewed")
    lines.append("- [ ] Sandbox tests + parity green")
    lines.append("- [ ] Query plans acceptable")
    lines.append("- [ ] Approve `execute_ddl` on production? (answer in chat)")
    return "\n".join(lines) + "\n"


def render_json(r: dict) -> dict:
    """Machine-readable subset of the safety report (consumed by the UI)."""
    return {
        "tool": r.get("tool", "alembic"),
        "apply_ok": bool(r.get("apply_ok")),
        "test_ok": bool(r.get("test_ok")),
        "parity_ok": r.get("parity_ok"),  # None when no parity SQL was given
        "diff": r.get("diff", {}),
        "explain": r.get("explain", []),
    }
