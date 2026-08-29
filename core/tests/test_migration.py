"""TDD tests for the migration phase classifier and lock analyzer."""
from pathlib import Path
import pytest
from schemaforge_core.migration import (
    classify,
    validate_phase,
    PhaseClassification,
    analyze_locks,
    LockReport,
)

# A single-migration file that does expand+backfill+contract in one upgrade()
# (the current demo 0002 shape). validate_phase("expand") MUST reject it.
MIXED = '''\
"""0002 split users."""
from alembic import op
import sqlalchemy as sa
revision = "0002"; down_revision = "0001"

def upgrade() -> None:
    op.create_table("user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("address", sa.String(255), nullable=False))
    op.execute("INSERT INTO user_profiles (user_id, address) SELECT id, address FROM users")
    op.drop_column("users", "address")

def downgrade() -> None:
    op.add_column("users", sa.Column("address", sa.String(255), nullable=True))
    op.drop_table("user_profiles")
'''

EXPAND_ONLY = '''\
"""0002a expand: additive only."""
from alembic import op
import sqlalchemy as sa
revision = "0002a"; down_revision = "0001"

def upgrade() -> None:
    op.create_table("user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("address", sa.String(255), nullable=False))
    op.execute("INSERT INTO user_profiles (user_id, address) SELECT id, address FROM users")

def downgrade() -> None:
    op.drop_table("user_profiles")
'''

CONTRACT_ONLY = '''\
"""0002b contract: drops only."""
from alembic import op
revision = "0002b"; down_revision = "0002a"

def upgrade() -> None:
    op.drop_column("users", "address")

def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column("users", sa.Column("address", sa.String(255), nullable=True))
'''


def _write(tmp_path: Path, name: str, src: str) -> Path:
    p = tmp_path / name
    p.write_text(src)
    return p


def test_classify_splits_ops_into_phases(tmp_path):
    f = _write(tmp_path, "0002.py", MIXED)
    c = classify(f)
    assert isinstance(c, PhaseClassification)
    assert any("create_table" in o.source for o in c.expand)
    assert any("INSERT INTO user_profiles" in o.source for o in c.expand)  # backfill is expand
    assert any("drop_column" in o.source for o in c.contract)
    assert not c.unclassified


def test_validate_phase_expand_retracts_contract_ops(tmp_path):
    f = _write(tmp_path, "0002.py", MIXED)
    with pytest.raises(ValueError, match="expand migration contains contract ops"):
        validate_phase(f, "expand")


def test_validate_phase_expand_accepts_expand_only(tmp_path):
    f = _write(tmp_path, "0002a.py", EXPAND_ONLY)
    validate_phase(f, "expand")  # must not raise


def test_validate_phase_contract_accepts_contract_only(tmp_path):
    f = _write(tmp_path, "0002b.py", CONTRACT_ONLY)
    validate_phase(f, "contract")  # must not raise


def test_validate_phase_contract_rejects_expand_ops(tmp_path):
    f = _write(tmp_path, "0002a.py", EXPAND_ONLY)
    with pytest.raises(ValueError, match="contract migration contains expand ops"):
        validate_phase(f, "contract")


def test_alter_column_set_not_null_is_contract(tmp_path):
    src = '''\
from alembic import op
revision="x"; down_revision="y"
def upgrade():
    op.add_column("t", op.Column("c", sa.Integer(), nullable=True))
    op.alter_column("t", "c", nullable=False)
'''
    # sa not imported — classify reads kwargs, not the sa name, so it parses fine
    f = _write(tmp_path, "alter.py", src)
    c = classify(f)
    assert any("alter_column" in o.source and o.kind == "contract" for o in c.contract)


def test_analyze_locks_flags_set_not_null_as_dangerous(tmp_path):
    src = '''\
from alembic import op
revision="x"; down_revision="y"
def upgrade():
    op.add_column("t", __import__("sqlalchemy").Column("c", __import__("sqlalchemy").Integer(), nullable=True))
    op.alter_column("t", "c", nullable=False)
'''
    f = _write(tmp_path, "alter.py", src)
    reports = analyze_locks(f)
    setnotnull = [r for r in reports if "SET NOT NULL" in r.reason or "alter_column" in r.statement]
    assert any(r.risk == "dangerous" for r in reports)
    assert any("CHECK" in r.alternative for r in reports)  # the online alternative


def test_analyze_locks_create_table_is_safe(tmp_path):
    f = _write(tmp_path, "0002a.py", EXPAND_ONLY)
    reports = analyze_locks(f)
    create = [r for r in reports if "create_table" in r.statement]
    assert create and create[0].risk == "safe"


def test_analyze_locks_flags_update_backfill_as_dangerous(tmp_path):
    # A large UPDATE backfill (op.execute("UPDATE ...")) holds row locks for the
    # whole transaction -- flagged dangerous, mirroring the raw-SQL path.
    src = '''\
from alembic import op
revision="x"; down_revision="y"

def upgrade():
    op.execute("UPDATE users SET address = '' WHERE address IS NULL")
'''
    f = _write(tmp_path, "backfill.py", src)
    reports = analyze_locks(f)
    upd = [r for r in reports if r.reason.startswith("UPDATE")]
    assert upd and upd[0].risk == "dangerous"
    assert upd[0].lock == "RowExclusive"
    assert upd[0].alternative
