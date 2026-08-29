"""SQL-migration phase classification, validation, and lock analysis.

Used by raw-SQL migrations (Drizzle / plain ``.sql``), sharing the same
``_sql_kind`` verb taxonomy as the Alembic ``op.*`` path so a migration is
classified identically regardless of authoring tool.
"""
from __future__ import annotations

import re
from pathlib import Path

from .migration import LockReport, OpClass, PhaseClassification, _sql_kind


def _split_sql_statements(sql: str):
    """Yield ``(lineno, statement)`` tuples for a SQL string.

    Aware of single-quoted strings ('' escapes a quote), PostgreSQL dollar
    quotes (``$tag$...$tag$`` and ``$$...$$``), ``--`` line comments, and
    ``/* */`` block comments. A space is emitted where a comment is stripped so
    adjacent tokens do not merge (``CREATE/* x */TABLE`` -> ``CREATE TABLE``).
    """
    buf: list[str] = []
    buf_start: int | None = None
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            if buf_start is None:
                buf_start = i
            buf.append(ch)
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        buf.append("''")
                        j += 2
                        continue
                    buf.append("'")
                    j += 1
                    break
                buf.append(sql[j])
                j += 1
            i = j
            continue
        if ch == "$":
            m = re.match(r"\$(\w*)\$", sql[i:])
            if m:
                if buf_start is None:
                    buf_start = i
                tag = m.group(1)
                close = "$" + tag + "$"
                j = i + m.end()
                k = sql.find(close, j)
                if k == -1:
                    buf.append(sql[i:])
                    i = n
                else:
                    buf.append(sql[i:k + len(close)])
                    i = k + len(close)
                continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            buf.append(" ")  # separator so tokens don't merge across a comment
            nl = sql.find("\n", i)
            i = nl if nl != -1 else n
            continue
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            buf.append(" ")  # separator so CREATE/* */TABLE -> CREATE TABLE
            end = sql.find("*/", i + 2)
            i = (end + 2) if end != -1 else n
            continue
        if ch.isspace():
            if buf_start is not None:
                buf.append(ch)
            i += 1
            continue
        if buf_start is None:
            buf_start = i
        buf.append(ch)
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt and stmt != ";":
                yield (sql.count("\n", 0, buf_start) + 1, stmt[:-1] if stmt.endswith(";") else stmt)
            buf = []
            buf_start = None
        i += 1
    stmt = "".join(buf).strip()
    if stmt and stmt != ";":
        yield (sql.count("\n", 0, buf_start or 0) + 1, stmt[:-1] if stmt.endswith(";") else stmt)


def classify_sql(file_path: str | Path) -> PhaseClassification:
    """Classify each statement of a raw-SQL migration into a phase.

    Returns a :class:`PhaseClassification` whose ``expand`` / ``contract`` /
    ``neutral`` / ``unclassified`` lists hold one :class:`OpClass` per statement,
    so a SQL migration is classified identically to the Alembic ``op.*`` path.
    """
    src = Path(file_path).read_text()
    cls = PhaseClassification()
    for lineno, stmt in _split_sql_statements(src):
        kind, label = _sql_kind(stmt)
        cls_attr = kind if kind in ("expand", "contract", "neutral", "unclassified") else "unclassified"
        getattr(cls, cls_attr).append(
            OpClass(source=stmt, kind=kind, lineno=lineno, end_lineno=lineno, reason=label)
        )
    return cls


def validate_phase_sql(file_path: str | Path, phase: str) -> None:
    """Raise :class:`ValueError` unless ``file_path`` is phase-pure.

    phase="expand"   -> only expand + neutral statements (no contract).
    phase="contract" -> only contract + neutral statements (no expand).
    Any unclassified statement is rejected (the author must classify it
    manually).  Mirrors :func:`schemaforge_core.migration.validate_phase`.
    """
    if phase not in ("expand", "contract"):
        raise ValueError(f"phase must be 'expand' or 'contract', got {phase!r}")
    cls = classify_sql(file_path)
    if cls.has_unclassified:
        ops = ", ".join(f"L{o.lineno}: {o.reason}" for o in cls.unclassified)
        raise ValueError(f"unclassified ops — classify manually: {ops}")
    if phase == "expand" and cls.contract:
        ops = ", ".join(f"L{o.lineno}: {o.source.splitlines()[0]}" for o in cls.contract)
        raise ValueError(f"expand migration contains contract ops: {ops}")
    if phase == "contract" and cls.expand:
        ops = ", ".join(f"L{o.lineno}: {o.source.splitlines()[0]}" for o in cls.expand)
        raise ValueError(f"contract migration contains expand ops: {ops}")


def _lock_for_sql(stmt: str, lineno: int) -> LockReport:
    """Lock / rewrites / risk / alternative for a single SQL statement.

    Lock semantics follow PostgreSQL 11+: ADD/DROP COLUMN and DROP NOT NULL are
    metadata-only (a brief ``AccessExclusive`` lock, no table rewrite), so they
    are reported as ``brief-lock`` rather than ``dangerous``.  SET NOT NULL and
    type changes still require a full table scan/rewrite and stay ``dangerous``.
    """
    s = stmt.strip()
    first = s.splitlines()[0] if s else ""

    if re.match(r"insert\s+into\b.*?\bselect\b", s, re.I | re.DOTALL):
        return LockReport(
            statement=first, lineno=lineno, lock="Share", rewrites=False, risk="dangerous",
            alternative="backfill in batches (keyset/LIMIT-OFFSET) to avoid a long Share lock on the source table")
    if re.match(r"insert\b", s, re.I):
        return LockReport(statement=first, lineno=lineno, lock="none", rewrites=False, risk="safe", alternative="")
    if re.match(r"create\s+(unique\s+)?index\b", s, re.I):
        return LockReport(
            statement=first, lineno=lineno, lock="Share", rewrites=False, risk="brief-lock",
            alternative="CREATE INDEX CONCURRENTLY (must run outside a transaction — separate execute_ddl call, not execute_migration)")
    if re.match(r"create\b", s, re.I):
        return LockReport(statement=first, lineno=lineno, lock="none", rewrites=False, risk="safe", alternative="")
    if re.match(r"(drop|truncate)\b", s, re.I):
        return LockReport(
            statement=first, lineno=lineno, lock="AccessExclusive", rewrites=False, risk="brief-lock",
            alternative="safe once contract-gate is clean (no code reads the dropped object)")
    if re.match(r"update\b", s, re.I):
        return LockReport(
            statement=first, lineno=lineno, lock="RowExclusive", rewrites=False, risk="brief-lock",
            alternative="batch the UPDATE (keyset) to keep transactions short")
    if re.match(r"alter\b", s, re.I):
        # SET NOT NULL — full table scan, rewrites/locks heavily.
        if re.search(r"\bset\s+not\s+null\b", s, re.I):
            return LockReport(
                statement=first, lineno=lineno, lock="AccessExclusive", rewrites=True, risk="dangerous",
                alternative="add CHECK (col IS NOT NULL) NOT VALID, VALIDATE CONSTRAINT (Share, non-blocking), then ALTER ... SET NOT NULL becomes metadata-only")
        # DROP NOT NULL — constraint relaxation, metadata-only on PG11+.
        if re.search(r"\bdrop\s+not\s+null\b", s, re.I):
            return LockReport(
                statement=first, lineno=lineno, lock="AccessExclusive", rewrites=False, risk="brief-lock",
                alternative="constraint relaxation; PG11+ metadata-only, no table rewrite")
        # DROP COLUMN — brief metadata lock, no rewrite on PG11+.
        if re.search(r"\bdrop\s+column\b", s, re.I):
            return LockReport(
                statement=first, lineno=lineno, lock="AccessExclusive", rewrites=False, risk="brief-lock",
                alternative="safe once contract-gate is clean (no code reads the column); PG11+ drops metadata only, no table rewrite")
        # ADD COLUMN — brief metadata lock, no rewrite (NULL or NOT NULL DEFAULT on PG11+).
        if re.search(r"\badd\s+column\b", s, re.I):
            return LockReport(
                statement=first, lineno=lineno, lock="AccessExclusive", rewrites=False, risk="brief-lock",
                alternative="ADD COLUMN ... NULL is metadata-only; ADD COLUMN NOT NULL DEFAULT is metadata-only on PG11+")
        # Generic ALTER (type change / rename / SET DEFAULT etc.) — assume a rewrite.
        return LockReport(
            statement=first, lineno=lineno, lock="AccessExclusive", rewrites=True, risk="dangerous",
            alternative="use the new-column + backfill + rename pattern, or split locking ALTERs across expand/contract")
    return LockReport(statement=first, lineno=lineno, lock="unknown", rewrites=False, risk="unclassified", alternative="review manually")


def analyze_locks_sql(file_path: str | Path) -> list[LockReport]:
    """Lock reports for each statement in a raw-SQL migration."""
    src = Path(file_path).read_text()
    return [_lock_for_sql(stmt, lineno) for lineno, stmt in _split_sql_statements(src)]
