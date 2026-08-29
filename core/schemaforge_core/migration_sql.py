"""Phase classification, validation, and lock analysis for raw-SQL migrations
(Drizzle / psql), reusing ``migration._sql_kind`` for the verb taxonomy.

Drizzle migrations are plain SQL (no Alembic ``op.*`` calls), so the engine
classifies each statement by its leading SQL verb via the shared
``_sql_kind`` helper and a comment- + dollar-quote-aware statement splitter.
"""
from __future__ import annotations

import re
from pathlib import Path

from .migration import LockReport, OpClass, PhaseClassification, _sql_kind


def _split_sql_statements(src: str) -> list[tuple[int, str]]:
    """Split SQL source into ``(lineno, statement)`` on ';' outside strings,
    line/block comments, and PostgreSQL dollar-quoted bodies. Comments are
    dropped from the statement text so verb detection is reliable."""
    stmts: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_start_idx: int | None = None
    i = 0
    n = len(src)
    in_single = in_double = False
    dollar_tag: str | None = None
    while i < n:
        ch = src[i]
        if in_single:
            if buf_start_idx is None:
                buf_start_idx = i
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and src[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_single = False
        elif in_double:
            if buf_start_idx is None:
                buf_start_idx = i
            buf.append(ch)
            if ch == '"':
                in_double = False
        elif dollar_tag is not None:
            if buf_start_idx is None:
                buf_start_idx = i
            buf.append(ch)
            if ch == "$" and src.startswith(dollar_tag, i):
                buf.append(src[i + 1:i + len(dollar_tag)])
                i += len(dollar_tag)
                dollar_tag = None
                continue
        else:
            if ch == "'":
                if buf_start_idx is None:
                    buf_start_idx = i
                in_single = True
                buf.append(ch)
            elif ch == '"':
                if buf_start_idx is None:
                    buf_start_idx = i
                in_double = True
                buf.append(ch)
            elif ch == "-" and i + 1 < n and src[i + 1] == "-":
                # line comment: skip to end of line (do not append)
                nl = src.find("\n", i)
                i = nl if nl != -1 else n
                continue
            elif ch == "/" and i + 1 < n and src[i + 1] == "*":
                # block comment: skip to closing */
                end = src.find("*/", i + 2)
                i = (end + 2) if end != -1 else n
                continue
            elif ch == "$":
                m = re.match(r"\$(\w*)\$", src[i:])
                if m:
                    if buf_start_idx is None:
                        buf_start_idx = i
                    dollar_tag = m.group(0)
                    buf.append(dollar_tag)
                    i += len(dollar_tag)
                    continue
                if buf_start_idx is None:
                    buf_start_idx = i
                buf.append(ch)
            elif ch == ";":
                stmt = "".join(buf).strip()
                if stmt and buf_start_idx is not None:
                    lineno = src.count("\n", 0, buf_start_idx) + 1
                    stmts.append((lineno, stmt))
                buf = []
                buf_start_idx = None
            else:
                if buf_start_idx is None and ch not in " \t\r\n":
                    buf_start_idx = i
                buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail and buf_start_idx is not None:
        lineno = src.count("\n", 0, buf_start_idx) + 1
        stmts.append((lineno, tail))
    return stmts


def classify_sql(file_path: str | Path) -> PhaseClassification:
    """Classify each SQL statement of a raw-SQL migration by phase."""
    src = Path(file_path).read_text(encoding="utf-8")
    cls = PhaseClassification()
    for lineno, stmt in _split_sql_statements(src):
        kind, reason = _sql_kind(stmt)
        cls_attr = getattr(cls, kind)  # expand | contract | neutral | unclassified
        cls_attr.append(OpClass(
            source=stmt, kind=kind, reason=reason,
            lineno=lineno, end_lineno=lineno,
        ))
    return cls


def validate_phase_sql(file_path: str | Path, phase: str) -> None:
    """Raise ValueError unless the SQL migration is phase-pure for ``phase``."""
    if phase not in ("expand", "contract"):
        raise ValueError(f"phase must be 'expand' or 'contract', got {phase!r}")
    cls = classify_sql(file_path)
    if cls.has_unclassified:
        ops = ", ".join(f"L{o.lineno}: {o.reason}" for o in cls.unclassified)
        raise ValueError(f"unclassified statements — classify manually: {ops}")
    if phase == "expand" and cls.contract:
        ops = ", ".join(o.source.splitlines()[0] for o in cls.contract)
        raise ValueError(f"expand migration contains contract ops: {ops}")
    if phase == "contract" and cls.expand:
        ops = ", ".join(o.source.splitlines()[0] for o in cls.expand)
        raise ValueError(f"contract migration contains expand ops: {ops}")


def _lock_for_sql(stmt: str) -> tuple[str, bool, str, str]:
    """Return (lock, rewrites, risk, alternative) for a SQL statement."""
    head = stmt.lstrip().split(None, 1)[0].upper() if stmt.strip() else ""
    if head in ("CREATE", "INSERT"):
        return ("none", False, "safe", "additive — no blocking lock")
    if head in ("ALTER", "DROP", "TRUNCATE"):
        return (
            "AccessExclusive", True, "dangerous",
            "split expand/contract; use pg_repack for an online rewrite",
        )
    return ("unknown", False, "brief-lock", "review manually")


def analyze_locks_sql(file_path: str | Path) -> list[LockReport]:
    """Report lock impact + an online alternative for each SQL statement."""
    src = Path(file_path).read_text(encoding="utf-8")
    reports: list[LockReport] = []
    for lineno, stmt in _split_sql_statements(src):
        lock, rewrites, risk, alt = _lock_for_sql(stmt)
        reports.append(LockReport(
            statement=stmt.splitlines()[0][:120], lineno=lineno,
            lock=lock, rewrites=rewrites, risk=risk, alternative=alt, reason="",
        ))
    return reports
