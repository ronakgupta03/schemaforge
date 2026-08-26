from schemaforge_core.db_snapshot import diff_tables
from schemaforge_core.models import ColumnInfo, DBSnapshot, TableInfo


def _snap(tables: dict[str, list[tuple[str, str]]]) -> DBSnapshot:
    snap = DBSnapshot()
    for name, cols in tables.items():
        snap.tables[name] = TableInfo(
            name=name, columns=[ColumnInfo(name=c, data_type="varchar", nullable=False) for c in cols]
        )
    return snap


def test_diff_detects_split_shape():
    before = _snap({"users": ["id", "email", "address", "date_of_birth"]})
    after = _snap(
        {
            "users": ["id", "email"],
            "user_profiles": ["id", "user_id", "address", "date_of_birth"],
        }
    )
    d = diff_tables(before, after)
    assert d["added_tables"] == ["user_profiles"]
    assert d["removed_tables"] == []
    assert d["removed_columns"] == ["users.address", "users.date_of_birth"]
    assert d["added_columns"] == []
