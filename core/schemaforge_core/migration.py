"""Phase classification, validation, and lock analysis for Alembic migrations
— the deterministic core of SchemaForge's zero-downtime model.

Zero-downtime means: apply an additive EXPAND migration now (safe under live
traffic), then apply the destructive CONTRACT migration later, only after a
deterministic check confirms no live code reads what is being removed. The LLM
authors the migrations; this module VALIDATES them (expand-only? contract-only?)
and will GATE the contract (Task 2) — it never guesses at the codebase.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

# op.<name> calls that are purely additive (safe on a live DB).
_EXPAND_OPS = frozenset({
    "create_table", "create_index", "create_unique_constraint",
    "create_foreign_key", "create_check_constraint", "add_column",
    "add_constraint", "rename_table",  # rename is a brief metadata swap
})
# op.<name> calls that remove schema (contract phase only).
_CONTRACT_OPS = frozenset({
    "drop_table", "drop_index", "drop_constraint", "drop_column",
})


@dataclass
class OpClass:
    """A single op.* call classified into a migration phase."""
    source: str          # verbatim source text of the call
    kind: str            # expand | contract | neutral | unclassified
    lineno: int
    end_lineno: int
    reason: str


@dataclass
class PhaseClassification:
    expand: list[OpClass] = field(default_factory=list)
    contract: list[OpClass] = field(default_factory=list)
    neutral: list[OpClass] = field(default_factory=list)
    unclassified: list[OpClass] = field(default_factory=list)

    @property
    def has_unclassified(self) -> bool:
        return bool(self.unclassified)


@dataclass
class LockReport:
    statement: str
    lineno: int
    lock: str          # none | Share | AccessExclusive | ShareUpdateExclusive
    rewrites: bool
    risk: str          # safe | brief-lock | dangerous
    alternative: str   # recommended online alternative, "" if none
    reason: str = ""


def _sql_kind(sql: str) -> tuple[str, str]:
    """Classify a raw SQL string used in op.execute(...)."""
    s = sql.strip()
    if re.match(r"UPDATE\s+alembic_version\b", s, re.I):
        return "neutral", "alembic version stamping"
    if re.match(r"UPDATE\b", s, re.I):
        # A data backfill UPDATE is additive work belonging to the expand
        # phase (it mutates rows, not schema). Lock analysis flags it heavy.
        return "expand", "UPDATE (data backfill)"
    if re.match(r"INSERT\s+INTO\b.*?\bSELECT\b", s, re.I | re.DOTALL):
        # A guarded INSERT..SELECT (WHERE NOT EXISTS) is a reconciliation —
        # idempotent backfill of stragglers before the contract drops. It is
        # phase-neutral (legal in contract) because it cannot duplicate rows.
        if re.search(r"\bWHERE\s+NOT\s+EXISTS\b", s, re.I):
            return "neutral", "INSERT..SELECT reconciliation (WHERE NOT EXISTS)"
        return "expand", "INSERT..SELECT backfill into a new table"
    if re.match(r"INSERT\b", s, re.I):
        return "expand", "INSERT (additive)"
    if re.match(r"CREATE\b", s, re.I):
        return "expand", "CREATE (additive)"
    if re.match(r"(DROP|TRUNCATE)\b", s, re.I):
        return "contract", "DROP/TRUNCATE (destructive)"
    if re.match(r"ALTER\b", s, re.I):
        # Additive ALTER forms are expand-safe on a live DB (metadata-only on
        # PG11+): ADD COLUMN/CONSTRAINT, ALTER COLUMN ... SET DEFAULT,
        # DROP NOT NULL (constraint relaxation), VALIDATE CONSTRAINT.
        # Everything else (type change, rename, SET NOT NULL, DROP COLUMN,
        # SET TABLESPACE) is contractive/locking — mirroring the Alembic op.*
        # expand set (add_column/add_constraint are expand ops).
        if re.search(
            r"\badd\s+(?:column|constraint)\b|\bset\s+default\b|"
            r"\bdrop\s+not\s+null\b|\bvalidate\s+constraint\b",
            s, re.I,
        ):
            return "expand", ("ALTER (additive: ADD COLUMN/CONSTRAINT, SET DEFAULT, "
                              "DROP NOT NULL, VALIDATE CONSTRAINT)")
        return "contract", "ALTER (locking/destructive — review)"
    return "unclassified", "unrecognized SQL verb"


def _alter_column_kind(call: ast.Call) -> tuple[str, str]:
    """op.alter_column(...) is expand or contract depending on kwargs."""
    for kw in call.keywords:
        if kw.arg == "nullable" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
            return "contract", "alter_column SET NOT NULL (AccessExclusive + full scan)"
        if kw.arg in ("type_", "new_column_name"):
            return "contract", "alter_column type/rename (locking)"
    return "expand", "alter_column (additive e.g. server_default)"


def _as_op_call(stmt: ast.stmt) -> ast.Call | None:
    """Return the op.<name>(...) Call if `stmt` is an expression statement of one."""
    if not isinstance(stmt, ast.Expr):
        return None
    call = stmt.value
    if not isinstance(call, ast.Call):
        return None
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "op":
        return call
    return None


def classify(file_path: str | Path) -> PhaseClassification:
    """Parse an Alembic migration file and classify each op.* call in upgrade()."""
    src = Path(file_path).read_text()
    tree = ast.parse(src)
    lines = src.splitlines()

    upgrade = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            upgrade = node
            break
    if upgrade is None:
        raise ValueError(f"{file_path}: no upgrade() function found")

    cls = PhaseClassification()
    for stmt in upgrade.body:
        call = _as_op_call(stmt)
        if call is None:
            continue  # comments, imports, non-op statements
        name = call.func.attr
        source = "\n".join(lines[stmt.lineno - 1: stmt.end_lineno])
        if name in _EXPAND_OPS:
            kind, reason = "expand", f"op.{name}"
        elif name in _CONTRACT_OPS:
            kind, reason = "contract", f"op.{name}"
        elif name == "execute" and call.args:
            sql = call.args[0].value if isinstance(call.args[0], ast.Constant) else ""
            kind, reason = _sql_kind(str(sql))
        elif name == "alter_column":
            kind, reason = _alter_column_kind(call)
        else:
            kind, reason = "unclassified", f"op.{name} (unknown)"
        op = OpClass(
            source=source, kind=kind, reason=reason,
            lineno=stmt.lineno, end_lineno=stmt.end_lineno or stmt.lineno,
        )
        getattr(cls, kind).append(op)
    return cls


def validate_phase(file_path: str | Path, phase: str) -> None:
    """Raise ValueError unless `file_path`'s upgrade() is phase-pure.

    phase="expand"   -> only expand + neutral ops (no contract).
    phase="contract" -> only contract + neutral ops (no expand).
    Any unclassified op is rejected (the author must classify it manually).
    """
    if phase not in ("expand", "contract"):
        raise ValueError(f"phase must be 'expand' or 'contract', got {phase!r}")
    cls = classify(file_path)
    if cls.has_unclassified:
        ops = ", ".join(f"L{o.lineno}: {o.reason}" for o in cls.unclassified)
        raise ValueError(f"unclassified ops — classify manually: {ops}")
    if phase == "expand" and cls.contract:
        ops = ", ".join(f"L{o.lineno}: {o.source.splitlines()[0]}" for o in cls.contract)
        raise ValueError(f"expand migration contains contract ops: {ops}")
    if phase == "contract" and cls.expand:
        ops = ", ".join(f"L{o.lineno}: {o.source.splitlines()[0]}" for o in cls.expand)
        raise ValueError(f"contract migration contains expand ops: {ops}")


def _lock_for(op: OpClass) -> tuple[str, bool, str, str]:
    """Return (lock, rewrites, risk, alternative) for a classified op."""
    name_line = op.source.strip().splitlines()[0]
    # op.execute SQL string
    if op.reason.startswith("INSERT..SELECT"):
        return ("Share", False, "dangerous",
                "backfill in batches (LIMIT/OFFSET or keyset) to avoid a long Share lock on the source table")
    if op.reason.startswith("UPDATE"):
        # A large UPDATE backfill holds row locks for the whole transaction;
        # without a proof it is bounded/batched it is dangerous, consistent with
        # _sql_kind labelling UPDATE a data backfill whose lock analysis is heavy.
        return ("RowExclusive", False, "dangerous",
                "batch the UPDATE (keyset/LIMIT-OFFSET) to keep transactions short and avoid long row locks")
    if op.reason == "CREATE (additive)":
        return ("none", False, "safe", "")
    if op.reason.startswith("DROP/TRUNCATE"):
        return ("AccessExclusive", False, "brief-lock",
                "safe to apply once contract-gate is clean (no code reads the dropped object)")
    if op.reason.startswith("ALTER (locking"):
        return ("AccessExclusive", True, "dangerous",
                "use the new-column + backfill + rename pattern, or split SET NOT NULL into "
                "ADD CHECK (col IS NOT NULL) NOT VALID, VALIDATE CONSTRAINT (non-blocking), "
                "then ALTER ... SET NOT NULL becomes metadata-only")
    # op.<name> by call name
    if "create_table" in name_line:
        return ("none", False, "safe", "")
    if "create_index" in name_line:
        return ("Share", False, "brief-lock",
                "use CREATE INDEX CONCURRENTLY (must run outside a transaction — separate execute_ddl call, not execute_migration)")
    if "add_column" in name_line:
        return ("AccessExclusive", False, "brief-lock",
                "ADD COLUMN ... NULL is metadata-only; ADD COLUMN NOT NULL DEFAULT is metadata-only on PG11+")
    if "alter_column" in name_line and "SET NOT NULL" in op.reason:
        return ("AccessExclusive", True, "dangerous",
                "add CHECK (col IS NOT NULL) NOT VALID, VALIDATE CONSTRAINT (Share, non-blocking), "
                "then ALTER ... SET NOT NULL becomes metadata-only")
    if "drop_column" in name_line:
        return ("AccessExclusive", False, "brief-lock",
                "safe once contract-gate is clean (no code reads the column)")
    return ("unknown", False, "unclassified", "review manually")


def analyze_locks(file_path: str | Path) -> list[LockReport]:
    """Report lock impact + an online alternative for each op in upgrade()."""
    cls = classify(file_path)
    reports: list[LockReport] = []
    for op in cls.expand + cls.contract:
        lock, rewrites, risk, alt = _lock_for(op)
        reports.append(LockReport(
            statement=op.source.strip().splitlines()[0], lineno=op.lineno,
            lock=lock, rewrites=rewrites, risk=risk, alternative=alt,
            reason=op.reason))
    return reports
