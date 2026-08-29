"""Language and migration-tool detection for a source tree."""
from __future__ import annotations

import re
from pathlib import Path

_DRIZZLE_BUILDER = re.compile(r"\b(?:pgTable|sqliteTable|mysqlTable)\s*\(")
_SKIP_DIRS = {"node_modules", "dist", "build", ".git", ".next", "coverage"}
_SQL_DIRS = ("migrations", "drizzle")


def _iter_files(root: Path, suffixes: tuple[str, ...]):
    """Yield files under ``root`` whose suffix is in ``suffixes``, skipping
    vendored/build directories. Covers both ``.ts`` and ``.tsx``."""
    for p in sorted(root.rglob("*")):
        if p.suffix in suffixes and not any(part in _SKIP_DIRS for part in p.parts):
            yield p


def detect_language(app_dir: str) -> str:
    """Return 'ts' for a Drizzle ORM app, else 'python'."""
    root = Path(app_dir)
    for p in _iter_files(root, (".ts", ".tsx")):
        try:
            if _DRIZZLE_BUILDER.search(p.read_text(encoding="utf-8", errors="ignore")):
                return "ts"
        except OSError:
            continue
    if (root / "alembic.ini").exists():
        return "python"
    for p in _iter_files(root, (".py",)):
        try:
            if "sqlalchemy" in p.read_text(encoding="utf-8", errors="ignore").lower():
                return "python"
        except OSError:
            continue
    # default: ts if any .ts/.tsx exists, else python
    return "ts" if any(True for _ in _iter_files(root, (".ts", ".tsx"))) else "python"


def sql_migration_files(app_dir: str | Path) -> list[Path]:
    """All ``*.sql`` migration files under ``migrations/`` or ``drizzle/``,
    recursively, sorted deterministically.

    Shared by tool detection and the SQL verify apply step so the two agree on
    which files constitute the migration batch (nested folders and the
    ``drizzle/`` directory are included, not just top-level ``migrations/``).
    """
    root = Path(app_dir)
    files: list[Path] = []
    for d in _SQL_DIRS:
        dd = root / d
        if dd.is_dir():
            files.extend(sorted(dd.rglob("*.sql")))
    return sorted(files)


def detect_migration_tool(app_dir: str) -> str:
    """Return 'alembic' | 'sql' | 'none'.

    'sql' covers Drizzle (``drizzle.config.ts``) and any ``migrations/`` or
    ``drizzle/`` directory containing ``*.sql`` files.
    """
    root = Path(app_dir)
    if (root / "alembic.ini").exists():
        return "alembic"
    if (root / "drizzle.config.ts").exists():
        return "sql"
    if sql_migration_files(root):
        return "sql"
    return "none"
