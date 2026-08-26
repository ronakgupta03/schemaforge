"""Deterministic schema snapshot via pg_catalog / information_schema."""
from __future__ import annotations

from psycopg import Connection
from psycopg.rows import dict_row

from .models import DBSnapshot, TableInfo

TABLES_SQL = """
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name
"""

COLUMNS_SQL = """
SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position
"""

INDEXES_SQL = """
SELECT t.relname AS table_name,
       i.relname AS index_name,
       ix.indisunique AS is_unique,
       a.attname AS column_name,
       array_position(ix.indkey, a.attnum) AS col_pos
FROM pg_class t
JOIN pg_index ix ON t.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
WHERE t.relnamespace = 'public'::regnamespace
  AND t.relkind = 'r'
ORDER BY t.relname, i.relname, col_pos
"""

FKS_SQL = """
SELECT tc.table_name, kcu.column_name,
       ccu.table_name AS ref_table, ccu.column_name AS ref_column,
       tc.constraint_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
  ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
"""

ROWCOUNTS_SQL = """
SELECT relname, reltuples::bigint AS row_count
FROM pg_class
WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'
"""


def connect(dsn: str) -> Connection:
    return Connection.connect(dsn, row_factory=dict_row)


def snapshot(conn: Connection) -> DBSnapshot:
    snap = DBSnapshot()
    for row in conn.execute(TABLES_SQL):
        snap.tables[row["table_name"]] = TableInfo(name=row["table_name"])
    for row in conn.execute(COLUMNS_SQL):
        t = snap.tables.get(row["table_name"])
        if t is None:
            continue
        t.columns.append(
            _column_from_row(row)
        )
    for row in conn.execute(INDEXES_SQL):
        t = snap.tables.get(row["table_name"])
        if t is None:
            continue
        idx = next((i for i in t.indexes if i.name == row["index_name"]), None)
        if idx is None:
            idx = _IndexRow(name=row["index_name"], unique=row["is_unique"])
            t.indexes.append(idx)
        idx.columns.append(row["column_name"])
    for row in conn.execute(FKS_SQL):
        t = snap.tables.get(row["table_name"])
        if t is None:
            continue
        t.foreign_keys.append(
            _FKRow(
                name=row["constraint_name"],
                column=row["column_name"],
                ref_table=row["ref_table"],
                ref_column=row["ref_column"],
            )
        )
    for row in conn.execute(ROWCOUNTS_SQL):
        t = snap.tables.get(row["relname"])
        if t:
            t.row_count = row["row_count"]
    return snap


def _column_from_row(row):
    from .models import ColumnInfo

    return ColumnInfo(
        name=row["column_name"],
        data_type=row["data_type"],
        nullable=row["is_nullable"] == "YES",
        default=row["column_default"],
    )


def _IndexRow(*, name, unique):
    from .models import IndexInfo

    return IndexInfo(name=name, columns=[], unique=unique)


def _FKRow(*, name, column, ref_table, ref_column):
    from .models import ForeignKeyInfo

    return ForeignKeyInfo(
        name=name, column=column, ref_table=ref_table, ref_column=ref_column
    )


def diff_tables(before: DBSnapshot, after: DBSnapshot) -> dict[str, list[str]]:
    """Structural diff: added/removed tables and added/removed columns."""
    added_tables = sorted(set(after.tables) - set(before.tables))
    removed_tables = sorted(set(before.tables) - set(after.tables))
    added_cols: list[str] = []
    removed_cols: list[str] = []
    for name, t in after.tables.items():
        b = before.tables.get(name)
        if b is None:
            continue
        bcols = {c.name for c in b.columns}
        acols = {c.name for c in t.columns}
        added_cols += [f"{name}.{c}" for c in sorted(acols - bcols)]
        removed_cols += [f"{name}.{c}" for c in sorted(bcols - acols)]
    return {
        "added_tables": added_tables,
        "removed_tables": removed_tables,
        "added_columns": added_cols,
        "removed_columns": removed_cols,
    }
