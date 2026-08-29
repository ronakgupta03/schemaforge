"""Language and migration-tool detection for a source tree."""
from __future__ import annotations

import re
from pathlib import Path

_DRIZZLE_BUILDER = re.compile(r"\b(?:pgTable|sqliteTable|mysqlTable)\s*\(")
_SKIP_DIRS = {"node_modules", "dist", "build", ".git", ".next", "coverage"}


def _iter_files(root: Path, suffix: str):
    for p in root.rglob(f"*{suffix}"):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        yield p


def detect_language(app_dir: str) -> str:
    """Return 'ts' for a Drizzle ORM app, else 'python'."""
    root = Path(app_dir)
    for p in _iter_files(root, ".ts"):
        try:
            if _DRIZZLE_BUILDER.search(p.read_text(encoding="utf-8", errors="ignore")):
                return "ts"
        except OSError:
            continue
    if (root / "alembic.ini").exists():
        return "python"
    for p in _iter_files(root, ".py"):
        try:
            if "sqlalchemy" in p.read_text(encoding="utf-8", errors="ignore").lower():
                return "python"
        except OSError:
            continue
    # default: ts if any .ts exists, else python
    return "ts" if any(True for _ in _iter_files(root, ".ts")) else "python"


def detect_migration_tool(app_dir: str) -> str:
    """Return 'alembic' | 'sql' | 'none'.

    'sql' covers Drizzle (drizzle.config.ts) and any migrations/ dir of *.sql.
    """
    root = Path(app_dir)
    if (root / "alembic.ini").exists():
        return "alembic"
    if (root / "drizzle.config.ts").exists():
        return "sql"
    for d in ("migrations", "drizzle"):
        dd = root / d
        if dd.is_dir() and any(dd.rglob("*.sql")):
            return "sql"
    return "none"
