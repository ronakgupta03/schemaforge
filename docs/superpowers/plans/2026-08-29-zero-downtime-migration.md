# Zero-Downtime Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SchemaForge genuinely zero-downtime by splitting every migration into an additive EXPAND phase (applied now, safe under live traffic) and a later CONTRACT phase (the destructive cleanup), with the contract gated on a deterministic impact-graph check that no live code reads what is being removed.

**Architecture:** SchemaForge is a **generic agent** — it operates on *any* Postgres-backed GitHub repo, not the bundled `demo-app/`. The runtime separates **tooling** (this repo: the deterministic core, the MCP servers, the skill + bootstrap script) from the **target** (the operator's repo, cloned into the sandbox). The deterministic core (`schemaforge_core`) classifies Alembic op.* calls into phases, validates a migration is phase-pure (expand-only / contract-only), reports DDL lock impact, and gates the contract on column-level reverse reachability over the impact graph. The LLM agent authors the two phased migrations plus a backward-compatible dual-write app build for the expand window; `execute_migration` enforces phase purity mechanically at apply time. Zero-downtime holds by construction when the operator follows the expand → deploy → contract sequence, and the contract cannot be proposed until the impact graph is clean. The `demo-app/` directory is a **test fixture only** — it ships a `.sf-sandbox.env` profile declaring its own DB name / app dir / seed command; no demo-specific value lives in any runtime logic file.

**Tech Stack:** Python 3.12+ stdlib `ast`, Alembic, SQLAlchemy 2.0, FastMCP 1.x (mcp>=1.9,<2), psycopg3, the existing `sf-pipeline` console script, TrueForge agent manifest + skill.

## Global Constraints

- Python stdlib `ast` only for code analysis — no tree-sitter, no LLM parsing of the codebase (the existing invariant; this plan extends it, never breaks it).
- Console script is `sf-pipeline` (defined in `core/pyproject.toml`); never reference a bare `pipeline` command. `python -m schemaforge_core.pipeline ...` is also valid.
- Deterministic core must be testable with the repo venv at `.vevn/bin/python` (uv-created, no `pip` module — use `uv pip install --python .vevn/bin/python` or run `.vevn/bin/python -m pytest`). The eval kernel uses a different interpreter; run venv code via bash invoking `.vevn/bin/python` directly.
- Every substantive change goes through a Qodo-reviewed GitHub PR into `main` on `github.com/ronakgupta03/schemaforge` (the hackathon gate). Small doc-only normalizations may go direct, as established.
- The single-source-of-truth rule for the approval gate: `execute_migration`'s `destructiveHint` annotation and `require_approval_for_tools` are configured exactly once in `scripts/apply_agent.py`; `agent/instructions.md` and the README describe the behavior in prose but must not restate config values.
- SchemaForge philosophy: deterministic core for facts/analysis/gates; the LLM agent for planning, orchestration, explanation, and code generation. This plan adds deterministic validation + gating; migration authoring and dual-write code remain the agent's job.
- MCP server pin: `mcp>=1.9,<2` (FastMCP 1.x). `mcp.run(transport="streamable-http")` with `mcp.settings.host`/`mcp.settings.port`; no `host=`/`port=` kwargs.
- Column node id in the impact graph is `col_{_mid(table)}_{_mid(col)}` (verified in `impact_graph.py:21`); table node id is `table_{_mid(table)}`. `_mid` is the module-level slugifier in `impact_graph.py`.
- **No demo hardcodes in runtime logic** (production invariant): `sandbox_setup.sh`, the agent instructions, the skill, the deterministic core, and the MCP servers must contain zero `bookstore`/`users`/`ronakgupta03`/seed-count/`demo-app` literals. Per-target specifics (DB name, app subdir, seed command) are declared by the *target* repo in a `.sf-sandbox.env` data file that the generic bootstrap reads; the `demo-app/` fixture ships its own. The SchemaForge tooling repo URL is the one legitimate constant (it is the product, not a demo).

---

## File Structure

- **Create:** `skills/schemaforge-migration/sandbox_setup.sh` — generic repo-agnostic in-sandbox bootstrap (starts Postgres, clones the target repo into `/workspace/app`, installs deps + `schemaforge-core` from the tooling repo, runs the target's migrations via auto-detected tool, optional seed); reads a target-side `.sf-sandbox.env` profile.
- **Delete:** `scripts/sandbox_setup.sh`, `packages/cli/scripts/sandbox_setup.sh` — replaced by the skill copy (the only hardcode source).
- **Create:** `demo-app/.sf-sandbox.env` — the demo fixture's bootstrap profile (DB name, app dir, seed command) as data, not logic.
- **Move:** `scripts/seed_prod.sh`, `scripts/reset_prod_db.sh`, `scripts/prod-postgres/` → `demo-app/` — demo-only prod-seeding fixtures, relabeled out of the generic agent.
- **Modify:** `agent/instructions.md` — generic bootstrap (clone target into `/workspace/app`, run the skill's `sandbox_setup.sh`, ask the operator for `GITHUB_REPO_URL` if unset); remove every `bookstore`/`demo-app`/`ronakgupta03` literal.
- **Modify:** `skills/schemaforge-migration/SKILL.md` — mirror the generic bootstrap; no demo literals.
- **Modify:** `README.md` — document the generic operator setup (point SchemaForge at any repo via `.sf-sandbox.env`); mark `demo-app/` as a fixture.
- **Create:** `core/schemaforge_core/migration.py` — phase classification, `validate_phase`, `analyze_locks` (the deterministic zero-downtime core).
- **Modify:** `core/schemaforge_core/impact_graph.py` — add `impacted_by_columns(g, columns)` (the contract gate's reachability).
- **Modify:** `core/schemaforge_core/pipeline.py` — add `validate-phase`, `contract-gate`, `analyze-locks` subcommands.
- **Modify:** `core/schemaforge_core/__init__.py` — export the new public surface.
- **Create:** `core/tests/test_migration.py` — TDD tests for classification, validate_phase, analyze_locks.
- **Create:** `core/tests/test_contract_gate.py` — TDD tests for `impacted_by_columns` + the `contract-gate` subcommand.
- **Modify:** `mcp-servers/postgres-mcp/server.py` — add `phase` param to `execute_migration` (expand rejects contractive verbs).
- **Create:** `mcp-servers/postgres-mcp/test_phase.py` — TDD test for the expand-phase guard (run against a scratch DB).
- **Modify:** `agent/instructions.md` — rewrite the workflow into the two-phase expand→contract flow + dual-write contract.
- **Modify:** `skills/schemaforge-migration/SKILL.md` — mirror the two-phase workflow.
- **Create:** `reference/post-split/expand/alembic/versions/0002a_expand.py` — the expand half of the split (additive only).
- **Create:** `reference/post-split/contract/alembic/versions/0002b_contract.py` — the contract half (drops only).
- **Create:** `reference/post-split/expand/app/models.py` — dual-write models for the expand window (keeps old columns, adds the new table).
- **Modify:** `docs/...` and `README.md` — the operator zero-downtime protocol + the contract-gate guarantee.

---

### Task 0: De-hardcode the runtime — generic agent bootstrap (production-grade)

**Why first:** every later task must operate on a *generic* agent. Today the only runtime hardcode is `scripts/sandbox_setup.sh` (repo URL, `bookstore`, `cd demo-app`, seed counts). This task separates **tooling** (this repo: core + skill + bootstrap) from **target** (any Postgres-backed repo) and makes the sandbox bootstrap read a target-side `.sf-sandbox.env` data file. After this, `demo-app/` is a test fixture that declares its own needs; no demo value lives in any logic file.

**Files:**
- Create: `skills/schemaforge-migration/sandbox_setup.sh` (generic)
- Delete: `scripts/sandbox_setup.sh`, `packages/cli/scripts/sandbox_setup.sh`
- Create: `demo-app/.sf-sandbox.env` (demo fixture profile, data not logic)
- Move: `scripts/seed_prod.sh` → `demo-app/seed_prod.sh`; `scripts/reset_prod_db.sh` → `demo-app/reset_prod_db.sh`; `scripts/prod-postgres/` → `demo-app/prod-postgres/`
- Modify: `agent/instructions.md`, `skills/schemaforge-migration/SKILL.md` (generic bootstrap)
- Verify + commit + PR + Qodo

**The generic `sandbox_setup.sh` contract** — env vars, all overridable by the target's `.sf-sandbox.env`:
- `GITHUB_REPO_URL` — target repo cloned into `/workspace/app` (REQUIRED if not pre-cloned)
- `SANDBOX_DB_NAME` — in-sandbox DB name (default: repo slug, else `appdb`)
- `APP_DIR` — app subdir for migrations/seed (default: auto-detect first dir with `alembic.ini`, else repo root)
- `SANDBOX_SEED_CMD` — shell command from `APP_DIR` to seed; empty = skip (default: empty)
- `SF_TOOLING_REPO` — schemaforge tooling repo for `pip install ...#subdirectory=core` (default: the public product repo — the one legitimate constant)

- [ ] **Step 1: Write the generic `skills/schemaforge-migration/sandbox_setup.sh`**

```bash
#!/usr/bin/env bash
# Generic in-sandbox bootstrap for SchemaForge on any Postgres-backed repo.
# Reads env (overridable by the target's .sf-sandbox.env). No target-specific literals.
set -euo pipefail

WORK=/workspace; APP="$WORK/app"; VEN="$HOME/.sfenv"; ACT="$HOME/.sfenv-activate.sh"
SF_TOOLING_REPO="${SF_TOOLING_REPO:-https://github.com/ronakgupta03/schemaforge}"

run_postgres() { if [ "$(id -u)" = 0 ]; then su postgres -c "$1"; else sudo -u postgres bash -lc "$1"; fi; }

# 1. Postgres (install if missing, start, wait for TCP)
if ! command -v psql >/dev/null 2>&1 || [ ! -d /etc/postgresql ]; then
  sudo apt-get update -qq && sudo apt-get install -y -qq postgresql postgresql-contrib
fi
sudo service postgresql start 2>/dev/null || sudo pg_ctlcluster main start 2>/dev/null || true
for _ in $(seq 1 30); do pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1 && break; sleep 1; done
pg_isready -h 127.0.0.1 -p 5432 || { echo "postgres not ready on 5432"; exit 1; }

# 2. Clone the target repo into /workspace/app
if [ -n "${GITHUB_REPO_URL:-}" ] && [ ! -d "$APP/.git" ]; then git clone --depth 1 "$GITHUB_REPO_URL" "$APP"; fi
[ -d "$APP" ] || { echo "no app at $APP and GITHUB_REPO_URL unset"; exit 1; }

# 3. Source target profile(s), then auto-detect APP_DIR, then source APP_DIR profile
[ -f "$APP/.sf-sandbox.env" ] && { set -a; . "$APP/.sf-sandbox.env"; set +a; }
if [ -z "${APP_DIR:-}" ]; then
  APP_DIR="$APP"
  for d in "$APP" "$APP"/*/; do [ -f "$d/alembic.ini" ] && { APP_DIR="$d"; break; }; done
fi
APP_DIR="${APP_DIR%/}"
[ -f "$APP_DIR/.sf-sandbox.env" ] && { set -a; . "$APP_DIR/.sf-sandbox.env"; set +a; }

# 4. DB name (default from repo slug)
if [ -z "${SANDBOX_DB_NAME:-}" ]; then
  SANDBOX_DB_NAME="$(basename "${GITHUB_REPO_URL:-app}" .git)"; [ -z "$SANDBOX_DB_NAME" ] && SANDBOX_DB_NAME=appdb
fi
run_postgres "createdb $SANDBOX_DB_NAME" 2>/dev/null || true
run_postgres "createdb ${SANDBOX_DB_NAME}_test" 2>/dev/null || true
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/$SANDBOX_DB_NAME"
TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/${SANDBOX_DB_NAME}_test"

# 5. venv + target deps + schemaforge-core from the tooling repo
[ -x "$VEN/bin/python" ] || python3 -m venv "$VEN"
"$VEN/bin/pip" install -q --upgrade pip
[ -f "$APP_DIR/requirements.txt" ] && "$VEN/bin/pip" install -q -r "$APP_DIR/requirements.txt"
[ -f "$APP/pyproject.toml" ] && "$VEN/bin/pip" install -q "$APP" 2>/dev/null || true
"$VEN/bin/pip" install -q "git+${SF_TOOLING_REPO}#subdirectory=core"

# 6. Migrations (auto-detect tool)
( cd "$APP_DIR" && \
  if [ -f alembic.ini ]; then "$VEN/bin/alembic" upgrade head; \
  elif [ -f manage.py ]; then "$VEN/bin/python" manage.py migrate; \
  else echo "no migration tool in $APP_DIR; skipping baseline"; fi )

# 7. Optional seed
[ -n "${SANDBOX_SEED_CMD:-}" ] && ( cd "$APP_DIR" && DATABASE_URL="$DATABASE_URL" eval "$SANDBOX_SEED_CMD" )

# 8. Activate script for later shells
cat > "$ACT" <<EOF
export PATH="$VEN/bin:\$PATH"
export DATABASE_URL="$DATABASE_URL"
export TEST_DATABASE_URL="$TEST_DATABASE_URL"
export APP_DIR="$APP_DIR"
export SANDBOX_DB_NAME="$SANDBOX_DB_NAME"
EOF
echo "SANDBOX_READY db=$SANDBOX_DB_NAME app=$APP_DIR"
```

`chmod +x` it. Note the demo profile lives at `demo-app/.sf-sandbox.env` (sourced in step 3 after auto-detect sets `APP_DIR=/workspace/app/demo-app`), so no `demo-app` literal appears in this script.

- [ ] **Step 2: Create `demo-app/.sf-sandbox.env` (the demo fixture's profile)**

```bash
# SchemaForge demo fixture profile. Declares THIS fixture's sandbox needs as data.
# The generic sandbox_setup.sh reads it; no demo value lives in tooling logic.
SANDBOX_DB_NAME=bookstore
SANDBOX_SEED_CMD=python seed.py 100000 1000
```

(`APP_DIR` is auto-detected as `demo-app` because it holds `alembic.ini`; no need to set it here.)

- [ ] **Step 3: Move demo-only scripts under `demo-app/` and delete the old bootstraps**

```bash
git mv scripts/seed_prod.sh demo-app/seed_prod.sh
git mv scripts/reset_prod_db.sh demo-app/reset_prod_db.sh
git mv scripts/prod-postgres demo-app/prod-postgres
git rm scripts/sandbox_setup.sh packages/cli/scripts/sandbox_setup.sh
```
These seed the demo's prod DB for the demo video — they are fixtures, not part of the generic agent. Relabel any internal `cd demo-app` in them is fine (they live inside the fixture now). Update README quickstart to call them from `demo-app/`.

- [ ] **Step 4: Rewrite the `agent/instructions.md` bootstrap section (generic)**

Replace the existing clone+`cd demo-app` bootstrap with:

```markdown
## Sandbox bootstrap (generic)

Clone the operator's target app and bootstrap an in-sandbox Postgres + tooling:

1. If `GITHUB_REPO_URL` is set in the environment, use it. Otherwise ask the operator
   for the GitHub URL of the app you are migrating. Do NOT assume any specific repo.
2. Run the generic bootstrap (it ships with this skill):
   `bash /opt/tfy/skills/schemaforge-migration/sandbox_setup.sh`
   It starts an in-sandbox Postgres, clones the target into `/workspace/app`, installs
   the app's deps + the SchemaForge core, runs the app's migrations (alembic/django
   auto-detected), and seeds if the repo declares `SANDBOX_SEED_CMD` in `.sf-sandbox.env`.
3. Source the activation script in every later shell: `. $HOME/.sfenv-activate.sh`.
   This sets `DATABASE_URL` (in-sandbox), `TEST_DATABASE_URL`, and `APP_DIR`.

All analysis runs against `$APP_DIR` (the target app) and the in-sandbox DB.
Production/cloud DB access is ONLY via the host-side `postgres-prod` MCP tools.
```

Grep-check `agent/instructions.md` is free of `bookstore`/`users`/`ronakgupta03`/`demo-app`/`0001`/`100000` literals (except inside code-fence examples clearly marked as the demo).

- [ ] **Step 5: Mirror the generic bootstrap in `skills/schemaforge-migration/SKILL.md`**

Same bootstrap text as Step 4 (the skill body is what loads on demand in the sandbox). Remove any `cd demo-app` / `bookstore` literal. Keep the conditional "if the app ships seed data, load it" phrasing (already generic).

- [ ] **Step 6: Verify `scripts/apply_agent.py` has no demo literals**

`apply_agent.py` reads `SCHEMAFORGE_MODEL` / `GITHUB_REPO_URL` from env and builds the manifest; it should contain no `bookstore`/`users`/`ronakgupta03` literal. If the skill import still hardcodes a repo, ensure it uses `$GITHUB_REPO_URL` (the operator's target), and that `SF_TOOLING_REPO` (the schemaforge repo for the skill source) is the only product constant. No functional change expected — verify and move on.

- [ ] **Step 7: Update `README.md` operator setup**

Document the generic flow: install SchemaForge, point it at any repo by setting `GITHUB_REPO_URL` (or letting the repo ship `.sf-sandbox.env`), register the agent. Mark `demo-app/` as "a fixture demonstrating the agent on a bookstore app; not required for your own repo." Update the quickstart so it does not call the deleted `scripts/sandbox_setup.sh`.

- [ ] **Step 8: Test the generic bootstrap two ways**

(a) **Demo through the generic path** — in a throwaway container or Daytona sandbox, with `GITHUB_REPO_URL=https://github.com/ronakgupta03/schemaforge`, run the new `sandbox_setup.sh`. Expect: clone into `/workspace/app`, auto-detect `APP_DIR=/workspace/app/demo-app`, source `demo-app/.sf-sandbox.env`, `SANDBOX_READY db=bookstore app=/workspace/app/demo-app`, alembic 0001 baseline, 100k users seeded, `sf-pipeline` on the venv PATH.

(b) **A minimal synthetic repo via pure auto-detection** — create a tiny repo with `app/models.py` (one SQLAlchemy table) + `alembic.ini` + an `0001_initial.py`, NO `.sf-sandbox.env`. Run `sandbox_setup.sh` with that URL. Expect: `SANDBOX_DB_NAME=<repo slug>`, `APP_DIR=/workspace/app` (alembic.ini at root), alembic upgrade head, no seed (cmd empty), `sf-pipeline` installed. This proves the zero-hardcode path works on a repo SchemaForge has never seen.

Both must print `SANDBOX_READY` and leave a working `sf-pipeline`.

- [ ] **Step 9: Commit + PR + Qodo**

```bash
git checkout -b feat/generic-bootstrap
git add skills/schemaforge-migration/sandbox_setup.sh demo-app/.sf-sandbox.env \
        demo-app/seed_prod.sh demo-app/reset_prod_db.sh demo-app/prod-postgres \
        agent/instructions.md skills/schemaforge-migration/SKILL.md README.md
git rm scripts/sandbox_setup.sh packages/cli/scripts/sandbox_setup.sh
git commit -m "feat: generic agent bootstrap (tooling/target separation, no demo hardcodes)"
gh pr create --base main --head feat/generic-bootstrap \
  --title "Generic agent bootstrap (production-grade, no demo hardcodes)" \
  --body "Relocates sandbox_setup.sh into the skill as a generic bootstrap; demo specifics become demo-app/.sf-sandbox.env data. Verified on the demo + a synthetic repo."
# comment /agentic_review; resolve findings; merge
```

**Acceptance:** `grep -rnE 'bookstore|ronakgupta03|100000' skills/ agent/instructions.md core/ mcp-servers/ packages/cli/mcp-servers/` returns only the `SF_TOOLING_REPO` default URL and clearly-marked demo examples; the synthetic-repo bootstrap prints `SANDBOX_READY` with no `.sf-sandbox.env`.

### Task 1: Op classifier + `validate_phase`

**Files:**
- Create: `core/schemaforge_core/migration.py`
- Create: `core/tests/test_migration.py`
- Test: `.vevn/bin/python -m pytest core/tests/test_migration.py -v`

**Interfaces:**
- Produces: `classify(file_path) -> PhaseClassification`, `validate_phase(file_path, phase) -> None` (raises `ValueError` if not phase-pure), `PhaseClassification` and `OpClass` dataclasses.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_migration.py`:

```python
"""TDD tests for the migration phase classifier."""
from pathlib import Path
import pytest
from schemaforge_core.migration import classify, validate_phase, PhaseClassification

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.vevn/bin/python -m pytest core/tests/test_migration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schemaforge_core.migration'`

- [ ] **Step 3: Implement `migration.py`**

Create `core/schemaforge_core/migration.py`:

```python
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


def _sql_kind(sql: str) -> tuple[str, str]:
    """Classify a raw SQL string used in op.execute(...)."""
    s = sql.strip()
    if re.match(r"UPDATE\s+alembic_version\b", s, re.I):
        return "neutral", "alembic version stamping"
    if re.match(r"INSERT\s+INTO\s+\S+\s+SELECT\b", s, re.I):
        return "expand", "INSERT..SELECT backfill into a new table"
    if re.match(r"CREATE\b", s, re.I):
        return "expand", "CREATE (additive)"
    if re.match(r"(DROP|TRUNCATE)\b", s, re.I):
        return "contract", "DROP/TRUNCATE (destructive)"
    if re.match(r"ALTER\b", s, re.I):
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.vevn/bin/python -m pytest core/tests/test_migration.py -v`
Expected: 6 passed.

- [ ] **Step 5: Wire the export + `validate-phase` CLI + commit**

Add to `core/schemaforge_core/__init__.py` (append within the existing import block, matching its style):

```python
from .migration import classify, validate_phase, PhaseClassification, OpClass
```

Add the `validate-phase` subcommand to `core/schemaforge_core/pipeline.py`. Command function (add near `cmd_impact`):

```python
def cmd_validate_phase(args: argparse.Namespace) -> None:
    from .migration import validate_phase
    try:
        validate_phase(args.migration, args.phase)
        print(f"validate-phase -> OK ({args.phase}-pure)")
    except ValueError as exc:
        print(f"validate-phase -> FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
```

Add `import sys` at the top of `pipeline.py` if not already present. Register the subcommand in `main()` (after the `impact` parser):

```python
    s = sub.add_parser("validate-phase")
    s.add_argument("--migration", required=True)
    s.add_argument("--phase", required=True, choices=["expand", "contract"])
    s.set_defaults(fn=cmd_validate_phase)
```

Verify the CLI works:

```bash
.vevn/bin/python -m schemaforge_core.pipeline validate-phase --migration reference/post-split/alembic/versions/0002_split_users.py --phase expand
```
Expected: exits 1 with `expand migration contains contract ops` (the single 0002 has drops).

Commit:

```bash
git add core/schemaforge_core/migration.py core/tests/test_migration.py core/schemaforge_core/__init__.py core/schemaforge_core/pipeline.py
git commit -m "feat(core): op classifier + validate_phase + validate-phase CLI for zero-downtime phasing"
```

---

### Task 2: Contract gate (`impacted_by_columns` + `contract-gate` subcommand)

**Files:**
- Modify: `core/schemaforge_core/impact_graph.py` (add `impacted_by_columns`)
- Modify: `core/schemaforge_core/pipeline.py` (add `contract-gate` subcommand)
- Create: `core/tests/test_contract_gate.py`
- Test: `.vevn/bin/python -m pytest core/tests/test_contract_gate.py -v`

**Interfaces:**
- Consumes: `impact_graph.build`, `impact_graph._mid`, `models.ImpactGraph/ImpactNode` (existing); `db_snapshot.connect`/`code_facts.collect_facts` (existing).
- Produces: `impact_graph.impacted_by_columns(g, columns) -> dict` (the contract-gate reachability); CLI `sf-pipeline contract-gate --db --code --columns --out`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_contract_gate.py`:

```python
"""TDD tests for the contract gate (column-level reverse reachability)."""
import json
from pathlib import Path
from schemaforge_core.models import DBSnapshot, TableInfo, ColumnInfo, CodeFacts, ModelFact, AttrAccess
from schemaforge_core.impact_graph import build, impacted_by_columns


def _graph_with_access():
    """users.address is read by an attr access -> NOT safe to drop yet."""
    snap = DBSnapshot(tables={
        "users": TableInfo(name="users", columns=[
            ColumnInfo(name="id", type="integer", nullable=False),
            ColumnInfo(name="address", type="character varying", nullable=False),
        ]),
    })
    facts = CodeFacts(
        models=[ModelFact(name="User", table="users", columns=["id", "address"],
                          file="app/models.py", line=5)],
        attr_accesses=[AttrAccess(model="User", column="address",
                                  file="app/routers/reports.py", line=12, function="addresses_report")],
    )
    return build(snap, facts)


def _graph_without_access():
    """No code reads users.address -> safe to drop."""
    snap = DBSnapshot(tables={
        "users": TableInfo(name="users", columns=[
            ColumnInfo(name="id", type="integer", nullable=False),
            ColumnInfo(name="address", type="character varying", nullable=False),
        ]),
    })
    facts = CodeFacts(
        models=[ModelFact(name="User", table="users", columns=["id"],
                          file="app/models.py", line=5)],
    )  # no attr_accesses for address
    return build(snap, facts)


def test_contract_gate_blocked_when_code_reads_column():
    g = _graph_with_access()
    r = impacted_by_columns(g, ["users.address"])
    assert r["safe"] is False
    assert any(b["kind"] == "attr" and "address" in b["label"] for b in r["blockers"])
    assert "app/routers/reports.py" in r["files"]


def test_contract_gate_safe_when_no_code_reads_column():
    g = _graph_without_access()
    r = impacted_by_columns(g, ["users.address"])
    assert r["safe"] is True
    assert r["blockers"] == []


def test_contract_gate_unknown_column_is_safe():
    g = _graph_without_access()
    r = impacted_by_columns(g, ["users.nonexistent"])
    assert r["safe"] is True  # no node -> no blockers
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.vevn/bin/python -m pytest core/tests/test_contract_gate.py -v`
Expected: FAIL with `ImportError: cannot import name 'impacted_by_columns'`

- [ ] **Step 3: Implement `impacted_by_columns`**

In `core/schemaforge_core/impact_graph.py`, add after `impacted_by` (after line 133):

```python
def impacted_by_columns(g: ImpactGraph, columns: list[str]) -> dict:
    """Reverse reachability from column nodes — the contract gate.

    `columns` are "table.column" names. A column is SAFE to drop iff this
    returns no code sites. Code sites are model/attr/rawsql/endpoint nodes
    (NOT the column/table/schema nodes themselves, which are structural).
    """
    start = {f"col_{_mid(c)}" for c in columns}
    rev: dict[str, list[str]] = defaultdict(list)
    for e in g.edges:
        rev[e.dst].append(e.src)
        rev[e.src].append(e.dst)
    seen: set[str] = set()
    stack = [n for n in start if n in g.nodes]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(rev.get(n, []))
    code_kinds = {"model", "attr", "rawsql", "endpoint"}
    blockers: list[dict] = []
    files: set[str] = set()
    for nid in seen:
        node = g.nodes[nid]
        if node.kind in code_kinds:
            blockers.append({"kind": node.kind, "label": node.label, "file": node.file})
            if node.file:
                files.add(node.file)
    blockers.sort(key=lambda b: (b.get("file") or "", b["label"]))
    return {
        "safe": not blockers,
        "columns": columns,
        "blockers": blockers,
        "files": sorted(files),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.vevn/bin/python -m pytest core/tests/test_contract_gate.py -v`
Expected: 3 passed.

- [ ] **Step 5: Add the `contract-gate` CLI subcommand**

In `core/schemaforge_core/pipeline.py`, add a command function near `cmd_impact` (after line 72):

```python
def cmd_contract_gate(args: argparse.Namespace) -> None:
    g = _load_graph(args.db, args.code)
    columns = [c.strip() for c in args.columns.split(",") if c.strip()]
    result = impacted_by_columns(g, columns)
    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(text)
    verdict = "SAFE" if result["safe"] else "BLOCKED"
    print(f"contract-gate -> {verdict} ({len(result['blockers'])} blocker(s))")
    if not result["safe"]:
        for b in result["blockers"]:
            print(f"  [{b['kind']}] {b['file']}:{b['label']}")
```

Add the import at the top of `pipeline.py` (next to the existing `from .impact_graph import ...`):

```python
from .impact_graph import impacted_by_columns
```

Register the subcommand in `main()` (after the `impact` parser, after line 230):

```python
    s = sub.add_parser("contract-gate")
    s.add_argument("--db", required=True)
    s.add_argument("--code", required=True)
    s.add_argument("--columns", required=True, help="comma-separated table.column names")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_contract_gate)
```

- [ ] **Step 6: Verify the CLI end-to-end**

Run:
```bash
.vevn/bin/python -m schemaforge_core.pipeline contract-gate \
  --db out/db.json --code out/code.json --columns users.address,users.date_of_birth
```
Expected: prints `contract-gate -> BLOCKED (N blocker(s))` with the reports endpoint + to_out helper listed (they read `users.address` / `users.date_of_birth` against the current pre-split code.json).

- [ ] **Step 7: Commit**

```bash
git add core/schemaforge_core/impact_graph.py core/schemaforge_core/pipeline.py core/tests/test_contract_gate.py
git commit -m "feat(core): contract-gate — column-level impact check before drop"
```

---

### Task 3: Lock analysis (`analyze_locks` + `analyze-locks` subcommand)

**Files:**
- Modify: `core/schemaforge_core/migration.py` (add `analyze_locks`, `LockReport`)
- Modify: `core/schemaforge_core/pipeline.py` (add `analyze-locks` subcommand)
- Modify: `core/tests/test_migration.py` (append lock tests)
- Test: `.vevn/bin/python -m pytest core/tests/test_migration.py -v`

**Interfaces:**
- Consumes: `migration.classify` (Task 1).
- Produces: `migration.analyze_locks(file_path) -> list[LockReport]`; CLI `sf-pipeline analyze-locks --migration <file> --out`.

- [ ] **Step 1: Write the failing tests**

Append to `core/tests/test_migration.py`:

```python
from schemaforge_core.migration import analyze_locks, LockReport


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.vevn/bin/python -m pytest core/tests/test_migration.py -k analyze_locks -v`
Expected: FAIL with `ImportError: cannot import name 'analyze_locks'`

- [ ] **Step 3: Implement `analyze_locks`**

Append to `core/schemaforge_core/migration.py`:

```python
@dataclass
class LockReport:
    statement: str
    lineno: int
    lock: str          # none | Share | AccessExclusive | ShareUpdateExclusive
    rewrites: bool
    risk: str          # safe | brief-lock | dangerous
    alternative: str   # recommended online alternative, "" if none


def _lock_for(op: OpClass) -> tuple[str, bool, str, str]:
    """Return (lock, rewrites, risk, alternative) for a classified op."""
    name_line = op.source.strip().splitlines()[0]
    # op.execute SQL string
    if op.reason.startswith("INSERT..SELECT"):
        return ("Share", False, "dangerous",
                "backfill in batches (LIMIT/OFFSET or keyset) to avoid a long Share lock on the source table")
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
            lock=lock, rewrites=rewrites, risk=risk, alternative=alt))
    return reports
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.vevn/bin/python -m pytest core/tests/test_migration.py -v`
Expected: all pass (8 total).

- [ ] **Step 5: Add the `analyze-locks` CLI subcommand**

In `core/schemaforge_core/pipeline.py`, add (after `cmd_contract_gate`):

```python
def cmd_analyze_locks(args: argparse.Namespace) -> None:
    from .migration import analyze_locks
    reports = analyze_locks(args.migration)
    data = [{"statement": r.statement, "line": r.lineno, "lock": r.lock,
             "rewrites": r.rewrites, "risk": r.risk, "alternative": r.alternative}
            for r in reports]
    text = json.dumps(data, indent=2)
    if args.out:
        Path(args.out).write_text(text)
    for r in reports:
        flag = "!" if r.risk == "dangerous" else ("." if r.risk == "brief-lock" else " ")
        print(f"{flag} L{r.lineno} [{r.lock}] {r.risk}: {r.statement[:70]}")
        if r.alternative:
            print(f"      -> {r.alternative}")
```

Register in `main()` (after the `contract-gate` parser):

```python
    s = sub.add_parser("analyze-locks")
    s.add_argument("--migration", required=True)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_analyze_locks)
```

- [ ] **Step 6: Verify on the reference 0002**

Run:
```bash
.vevn/bin/python -m schemaforge_core.pipeline analyze-locks \
  --migration reference/post-split/alembic/versions/0002_split_users.py
```
Expected: flags the two `drop_column` calls as `brief-lock` and any ALTER as `dangerous`; `create_table` as `safe`.

- [ ] **Step 7: Commit**

```bash
git add core/schemaforge_core/migration.py core/schemaforge_core/pipeline.py core/tests/test_migration.py
git commit -m "feat(core): analyze-locks — DDL lock impact + online alternatives"
```

---

### Task 4: `execute_migration(sql, phase)` — mechanical expand-phase guard

**Files:**
- Modify: `mcp-servers/postgres-mcp/server.py` (add `phase` param + contractive-verb rejection)
- Create: `mcp-servers/postgres-mcp/test_phase.py`
- Test: `.vevn/bin/python mcp-servers/postgres-mcp/test_phase.py` (against a scratch DB on :5434)

**Interfaces:**
- Consumes: the existing `_split_statements`, `_validate_migration_statement`, `_existing_tables`, `_conn` (existing).
- Produces: `execute_migration(sql: str, phase: str | None = None) -> str`; `phase="expand"` rejects any statement whose first verb is DROP/TRUNCATE/ALTER.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/postgres-mcp/test_phase.py`:

```python
"""Functional test: execute_migration(phase='expand') rejects contractive verbs.
Run against a scratch DB on :5434. Creates its own DB if needed.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from server import _validate_migration_statement  # noqa

# A regex-free unit check: the expand guard helper.
import re
_CONTRACTIVE_VERB = re.compile(r"^\s*(DROP|TRUNCATE|ALTER\b)", re.I)

def _expand_ok(stmt: str) -> bool:
    return not _CONTRACTIVE_VERB.match(stmt)

assert _expand_ok("CREATE TABLE user_profiles (id int)")
assert _expand_ok("INSERT INTO user_profiles (a) SELECT a FROM users")
assert not _expand_ok("DROP TABLE users")
assert not _expand_ok("ALTER TABLE users DROP COLUMN address")
print("expand-phase verb guard: OK")
```

- [ ] **Step 2: Run the test to verify the guard logic**

Run: `.vevn/bin/python mcp-servers/postgres-mcp/test_phase.py`
Expected: prints `expand-phase verb guard: OK`.

- [ ] **Step 3: Wire the guard into `execute_migration`**

In `mcp-servers/postgres-mcp/server.py`, add a module-level constant near the other regexes:

```python
_CONTRACTIVE_VERB = re.compile(r"^\s*(DROP|TRUNCATE|ALTER\b)", re.IGNORECASE)
```

Modify the `execute_migration` tool signature and body. Replace the `def execute_migration(sql: str) -> str:` line and its docstring/loop to add the `phase` param and guard. The new tool definition:

```python
@mcp.tool(
    annotations={"destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    description=(
        "Apply an Alembic migration batch (DDL + data backfill + version "
        "stamping) against the production database inside ONE transaction — a "
        "failure rolls back every earlier statement. Irreversible — the "
        "harness pauses this call for human approval. Pass phase='expand' for "
        "an additive migration: contractive verbs (DROP/TRUNCATE/ALTER) are "
        "rejected so an expand apply can never remove schema."
    ),
)
def execute_migration(sql: str, phase: str | None = None) -> str:
    """Run an `alembic upgrade <rev>:head --sql` batch on prod, atomically.

    phase='expand' rejects any statement whose first verb is DROP/TRUNCATE/ALTER
    (the expand migration must be purely additive).
    """
    statements = _split_statements(sql)
    if not statements:
        raise ValueError("empty migration batch")
    statements = [
        s for s in statements if not _TRANSACTION_FRAME.match(_strip_sql_comments(s))
    ]
    if not statements:
        raise ValueError("migration batch contains only transaction framing")
    for stmt in statements:
        _validate_migration_statement(stmt)
        if phase == "expand":
            clean = _strip_sql_comments(stmt)
            m = _CONTRACTIVE_VERB.match(clean)
            if m:
                raise ValueError(
                    f"expand-phase migration must be additive; contractive verb "
                    f"{m.group(1)!r} not allowed: {clean[:80]!r}"
                )
    with _conn(autocommit=False) as conn:
        pre = _existing_tables(conn)
        try:
            for i, stmt in enumerate(statements, 1):
                clean = _strip_sql_comments(stmt)
                m = _INSERT_INTO.match(clean)
                if m:
                    target = m.group(1).lower()
                    if target != "alembic_version" and target in pre:
                        raise ValueError(
                            f"backfill target {target!r} already exists — INSERT..SELECT "
                            "may only populate tables created by this migration"
                        )
                conn.execute(clean)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise RuntimeError(
                f"migration failed at statement {i}/{len(statements)} and rolled back: {exc}"
            ) from exc
    return f"applied {len(statements)} migration statement(s) in one transaction (phase={phase or 'full'})"
```

- [ ] **Step 4: Restart the postgres-mcp server and verify live**

Restart the hub-managed `postgres-mcp` process (or, if the user owns it, ask the user to restart `scripts/run_mcp_servers.sh`). Then verify the guard over the MCP protocol with proper Accept headers:

```bash
.vevn/bin/python - <<'EOF'
import json, re, httpx
H = {"Accept":"application/json, text/event-stream","Content-Type":"application/json"}
with httpx.Client(base_url="http://127.0.0.1:8001", timeout=15) as c:
    r = c.post("/mcp", headers=H, json={"jsonrpc":"2.0","id":1,"method":"initialize",
        "params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"0"}}})
    sid = r.headers.get("mcp-session-id"); h = {**H, "mcp-session-id": sid}
    c.post("/mcp", headers=h, json={"jsonrpc":"2.0","method":"notifications/initialized"})
    # expand batch containing a DROP -> must be rejected
    bad = "CREATE TABLE zt(a int); DROP TABLE zt;"
    out = None
    r2 = c.post("/mcp", headers=h, json={"jsonrpc":"2.0","id":2,"method":"tools/call",
        "params":{"name":"execute_migration","arguments":{"sql": bad, "phase":"expand"}}})
    raw = r2.text
    if r2.status_code == 202: raw = c.get("/mcp", headers=h).text
    m = re.search(r'data: (\{.*\})', raw, re.S)
    out = json.loads(m.group(1)) if m else json.loads(raw)
    print("reject DROP in expand ->", json.dumps(out.get("result", out))[:200])
EOF
```
Expected: an error result containing `contractive verb 'DROP' not allowed`.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/postgres-mcp/server.py mcp-servers/postgres-mcp/test_phase.py
git commit -m "feat(postgres-mcp): execute_migration phase='expand' rejects contractive verbs"
```

---

### Task 5: Two-phase agent workflow + dual-write contract

**Files:**
- Modify: `agent/instructions.md` (rewrite the Workflow section into expand→contract)
- Modify: `skills/schemaforge-migration/SKILL.md` (mirror)
- Verify: re-run `scripts/apply_agent.py` (with `.env` sourced) and confirm the live manifest instructions contain the two-phase flow.

**Interfaces:**
- Consumes: `sf-pipeline validate-phase`, `contract-gate`, `analyze-locks` (Tasks 1-3); `execute_migration(phase='expand')` (Task 4).
- Produces: the live agent's two-phase behavior. Behaviorally verified in Task 7, not unit-tested.

- [ ] **Step 1: Rewrite the Workflow section of `agent/instructions.md`**

Replace the `## Workflow (mirror of the skill — order matters)` section (lines 130-167) with the two-phase flow. The new section:

````markdown
## Workflow — zero-downtime, two phases

SchemaForge is zero-downtime ONLY when the operator follows the
expand → deploy → contract sequence. You NEVER apply a contract migration
in the same turn as an expand migration, and you NEVER propose a contract
until the deterministic contract-gate is clean.

### Phase 1 — EXPAND (apply now; additive, safe under live traffic)
1. Configuration check FIRST: confirm `postgres-prod.list_tables` succeeds;
   on `not configured`/connection error → STOP, ask for the DSN, wait.
   Confirm `GITHUB_REPO_URL`; ask if unset. Note the delivery instruction
   (PR / commit-only / artifact-only); ask if ambiguous.
2. Clarify the change (ask_user_question if genuinely ambiguous).
3. Spawn the two subagents (parallel): `db-analysis` (postgres-prod MCP
   tools) and `code-analysis` (sandbox `sf-pipeline facts`).
4. Merge into the impact graph; show the user the mermaid graph + impacted
   files/endpoints.
5. Author the EXPAND migration (`alembic/versions/<rev>a_<slug>.py`):
   additive only — `create_table`, `add_column` (nullable or with default),
   `create_index`, and `INSERT..SELECT` backfill. NO `drop_*`, NO
   `alter_column(..., nullable=False)`. Then validate it:
   `sf-pipeline validate-phase --migration <expand file> --phase expand`
   (must exit 0; fix any contract op it flags).
6. Author the DUAL-WRITE app build for the expand window: keep the old
   columns on the model (the expand migration did NOT drop them) AND add
   the new table/relationship; writes go to BOTH the old and new shapes so
   the running app keeps serving while the new shape is populated. Use the
   impact graph to find every endpoint that reads the old columns and make
   each one read the new shape with a fallback to the old (or stay on the
   old — both are safe while the old columns still exist).
7. Verify in the sandbox:
   `sf-pipeline verify --dir /workspace/app --dsn $DATABASE_URL --baseline out/db_before.json --parity-sql <parity> --queries <app queries> --explain-before out/explain_before.json --out out/report.md`
   Confirm migration PASS, tests PASS, parity PASS. The old columns still
   exist after expand, so parity = the old shape is unchanged AND the new
   table is backfilled.
8. Lock analysis: `sf-pipeline analyze-locks --migration <expand file>`.
   If any op is `dangerous` (e.g. SET NOT NULL), rework it into the safe
   alternative the report names BEFORE applying. CREATE INDEX CONCURRENTLY
   and the CHECK-constraint trick cannot run inside execute_migration's
   single transaction — emit those as a separate `execute_ddl` step or an
   operator manual note.
9. Present the expand safety report (markdown) and pause. You MUST call
   `ask_user_question` — Approve / Deny / Request changes — never end the
   turn silently after the report.
10. On approval: `cd /workspace/app && alembic upgrade <current>:head --sql > /workspace/out/expand.sql`,
    then call `postgres-prod.execute_migration` with that SQL and
    `phase='expand'`. After it returns, verify with `table_schema` +
    `row_count`.
11. Delivery — the expand PR: push the expand migration + dual-write app
    code to branch `schemaforge/<change-slug>-expand` via github MCP and
    open the PR (body = safety report + impact graph + lock report).
12. Tell the operator explicitly: "Expand applied. Deploy the dual-write
    app code from the PR. When deployed and stable, tell me 'contract
    <change-slug>' and I will run the contract gate and apply the cleanup."
    END THE TURN. Do NOT proceed to contract in the same turn.

### Phase 2 — CONTRACT (apply later; gated, destructive)
13. The operator triggers contract with "contract <change-slug>". Re-run
    `sf-pipeline facts` on the CURRENT repo (the code as deployed now) and
    rebuild the impact graph.
14. Run the contract gate for every column/table being removed:
    `sf-pipeline contract-gate --db out/db.json --code out/code.json --columns <table>.<col>,...`
    If `BLOCKED`: list every blocker (file:label) and STOP — tell the
    operator which code still reads the old columns and must be deployed
    first. Do NOT author or apply a contract migration while blocked.
15. If `SAFE`: author the CONTRACT migration (`<rev>b_<slug>.py`) with only
    the `drop_*` / `alter_column` cleanup, then
    `sf-pipeline validate-phase --migration <contract file> --phase contract`
    (must exit 0).
16. Author the FINAL app build: the model now reads ONLY the new shape
    (old columns removed). Verify in the sandbox (apply the contract
    migration, run the final tests, parity against the new shape, EXPLAIN
    before/after).
17. Present the contract safety report + the contract-gate verdict and
    pause (`ask_user_question` — Approve / Deny).
18. On approval: `alembic upgrade <current>:head --sql > out/contract.sql`,
    then `postgres-prod.execute_migration` with that SQL (phase defaults to
    full — contract contains the drops). Verify `table_schema` + `row_count`.
19. Delivery — the contract PR: push the contract migration + final app
    code to branch `schemaforge/<change-slug>-contract`, open the PR.

## Output contract
- End every phase with one status line + artifact paths.
- Impact graph: mermaid code block in chat AND saved to `out/graph.mmd`.
- Safety report: markdown; every number must come from a tool result or the
  engine; label estimates as estimates.
- The contract-gate verdict (SAFE/BLOCKED + blockers) is part of the
  contract report — never omit it.
- If a step fails twice, stop and report the failure with the exact error —
  do not improvise around safety invariants.
````

- [ ] **Step 2: Mirror the two-phase flow in `skills/schemaforge-migration/SKILL.md`**

Rewrite the skill's step list to match: expand (author additive migration → validate-phase expand → dual-write code → verify → analyze-locks → approve → execute_migration phase='expand' → expand PR → STOP), then contract (re-facts → contract-gate → if SAFE: author contract migration → validate-phase contract → final code → verify → approve → execute_migration → contract PR). Keep the skill's invariants (the app's tests are the API contract; never edit them; the downgrade orphan-guard DO block for backfilled columns).

- [ ] **Step 3: Re-register the live agent**

Run (with `.env` sourced so the model stays `cloudflare/deepseek-v4-flash`):
```bash
set -a && . ./.env && set +a && .vevn/bin/python scripts/apply_agent.py
```
Verify the live manifest instructions contain `validate-phase`, `contract-gate`, `phase='expand'`, and `expand → deploy → contract`.

- [ ] **Step 4: Commit**

```bash
git add agent/instructions.md skills/schemaforge-migration/SKILL.md
git commit -m "feat(agent): two-phase expand/contract workflow + dual-write contract"
```

---

### Task 6: Reference phased migrations + dual-write models + contract-gate fixture

**Files:**
- Create: `reference/post-split/expand/alembic/versions/0002a_expand.py`
- Create: `reference/post-split/contract/alembic/versions/0002b_contract.py`
- Create: `reference/post-split/expand/app/models.py` (dual-write)
- Verify: `validate-phase` passes on each; `contract-gate` SAFE against the dual-write/final code.

**Interfaces:**
- Consumes: `validate_phase`, `impacted_by_columns` (Tasks 1-2).
- Produces: the golden two-phase reference the demo and the agent compare against.

- [ ] **Step 1: Write the expand migration**

Create `reference/post-split/expand/alembic/versions/0002a_expand.py`:

```python
"""0002a expand: create user_profiles and backfill (additive only).

Zero-downtime phase 1. Safe to apply on a live database: creates a new table
and backfills it from users WITHOUT dropping or locking users for long. The
old columns (users.address, users.date_of_birth) remain in place so the
running application keeps serving.

Revision ID: 0002a
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002a"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=False, unique=True),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.String(length=10), nullable=True),
    )
    op.execute(
        "INSERT INTO user_profiles (user_id, address, date_of_birth) "
        "SELECT id, address, date_of_birth FROM users"
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
```

- [ ] **Step 2: Write the contract migration**

Create `reference/post-split/contract/alembic/versions/0002b_contract.py`:

```python
"""0002b contract: drop the moved columns (gated, destructive).

Zero-downtime phase 2. Applied ONLY after the operator deploys the final app
code and the contract-gate confirms no live code reads users.address or
users.date_of_birth. The drops are brief AccessExclusive locks; safe because
nothing reads the columns anymore.

Revision ID: 0002b
Revises: 0002a
"""
from alembic import op
import sqlalchemy as sa

revision = "0002b"
down_revision = "0002a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("users", "date_of_birth")
    op.drop_column("users", "address")


def downgrade() -> None:
    # Re-add the columns from user_profiles. Guarded: if any user lacks a
    # profile row, rollback is blocked rather than fabricating NULLs that
    # would violate NOT NULL on re-add (same edge Qodo caught on PR #15).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM users u
                LEFT JOIN user_profiles p ON p.user_id = u.id
                WHERE p.id IS NULL
            ) THEN
                RAISE EXCEPTION 'rollback blocked: users exist without a user_profiles row';
            END IF;
        END $$;
        """
    )
    op.add_column("users", sa.Column("address", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("date_of_birth", sa.String(length=10), nullable=True))
    op.execute(
        "UPDATE users u SET address = p.address, date_of_birth = p.date_of_birth "
        "FROM user_profiles p WHERE p.user_id = u.id"
    )
```

- [ ] **Step 3: Validate both with `validate-phase`**

```bash
.vevn/bin/python -m schemaforge_core.pipeline validate-phase --migration reference/post-split/expand/alembic/versions/0002a_expand.py --phase expand
.vevn/bin/python -m schemaforge_core.pipeline validate-phase --migration reference/post-split/contract/alembic/versions/0002b_contract.py --phase contract
```
Expected: both exit 0 (no output / exit 0). If `validate-phase` is not yet a registered subcommand, add it in Task 1's CLI wiring (it wraps `validate_phase`): add `cmd_validate_phase` that calls `validate_phase(args.migration, args.phase)` and a parser entry. (Include this in Task 1 Step 5 if not already.)

- [ ] **Step 4: Write the dual-write models for the expand window**

Create `reference/post-split/expand/app/models.py` — the User model KEEPS `address`/`date_of_birth` (expand did not drop them) AND adds `UserProfile` with a 1:1 relationship; the app writes to both during the expand window:

```python
"""Dual-write models for the expand window (zero-downtime phase 1).

The old columns (users.address, users.date_of_birth) still exist on the
table; the new user_profiles table is populated by the expand backfill and by
dual-writes from this app build. Reads stay on the old columns here for
simplicity — they are still present and correct. The FINAL models
(reference/post-split/app/models.py) move reads to user_profiles and drop the
old columns.
"""
from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from .db import Base


class User(Base):
    __tablename__ = "users"
    id = sa.Column(Integer, primary_key=True)  # sa imported below
    name = sa.Column(String(255), nullable=False)
    email = sa.Column(String(255), nullable=False, unique=True)
    # KEPT during expand — the running app still reads these.
    address = sa.Column(String(255), nullable=False)
    date_of_birth = sa.Column(String(10), nullable=True)
    profile = relationship("UserProfile", uselist=False, back_populates="user")


class UserProfile(Base):
    __tablename__ = "user_profiles"
    id = sa.Column(Integer, primary_key=True)
    user_id = sa.Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    address = sa.Column(String(255), nullable=False)
    date_of_birth = sa.Column(String(10), nullable=True)
    user = relationship("User", back_populates="profile")
```

(Add `import sqlalchemy as sa` at the top of the file; the snippet above uses `sa.` — ensure the import is present and the column types match the existing demo `models.py`.)

- [ ] **Step 5: Verify the contract-gate is SAFE against the final (post-split) code**

Build the impact graph from the final post-split code (which no longer reads `users.address`) and run:
```bash
.vevn/bin/python -m schemaforge_core.pipeline contract-gate \
  --db out/db.json --code out/code_final.json --columns users.address,users.date_of_birth
```
Expected: `SAFE (0 blockers)`. (This requires `out/code_final.json` = facts collected from the final post-split app; generate it with `sf-pipeline facts --app reference/post-split/app --out out/code_final.json`.)

- [ ] **Step 6: Commit**

```bash
git add reference/post-split/expand reference/post-split/contract
git commit -m "feat(reference): phased expand/contract migrations + dual-write models"
```

---

### Task 7: End-to-end two-phase sandbox verify + live demo

**Files:**
- Verify: the sandbox rehearsal (`scripts/rehearse_golden.sh` adapted) runs both phases.
- Verify: a live two-phase agent run (expand turn → contract gate → contract turn) against the prod DB on :5433.

**Interfaces:**
- Consumes: all of Tasks 1-6.
- Produces: proof that zero-downtime holds end-to-end (expand applies while the old columns remain; contract applies only after the gate is clean; the app serves throughout).

- [ ] **Step 1: Reset prod to pre-split**

```bash
docker compose -f scripts/prod-postgres/docker-compose.yml down -v
docker compose -f scripts/prod-postgres/docker-compose.yml up -d
# TCP readiness on 127.0.0.1:5433
bash scripts/seed_prod.sh   # 200k users / 5k books at alembic 0001
```

- [ ] **Step 2: Sandbox-rehearse the EXPAND phase**

In a Daytona sandbox (or the Docker rehearsal image), apply ONLY `0002a`:
```bash
cd /workspace/app && .vevn/bin/alembic upgrade 0001:0002a
```
Verify: `users` still has `address`/`date_of_birth`; `user_profiles` exists with 100k rows (sandbox seeded 100k); contract-gate against the CURRENT (pre-split) code is BLOCKED (the reports endpoint still reads `users.address`). This proves the gate correctly refuses contract while old code lives.

- [ ] **Step 3: Sandbox-rehearse the CONTRACT phase after deploying final code**

Swap the app code to the final post-split models (the expand-window reads move off `users.address`), rebuild `code.json`, run:
```bash
.vevn/bin/python -m schemaforge_core.pipeline contract-gate --db out/db.json --code out/code.json --columns users.address,users.date_of_birth
```
Expected: `SAFE (0 blockers)`. Then apply `0002b`:
```bash
cd /workspace/app && .vevn/bin/alembic upgrade 0002a:0002b
```
Verify: `users.address`/`users.date_of_birth` gone; `user_profiles` intact; parity holds; tests pass.

- [ ] **Step 4: Live two-phase agent run**

Create a live session with the locked split prompt. The agent should: analyze → author 0002a (validate-phase expand passes) → dual-write models → sandbox verify → analyze-locks → pause (ask_user_question) → on approval `execute_migration(phase='expand')` → expand PR → STOP and tell the operator to deploy + say "contract users". Then in a second turn ("contract users"): re-facts → contract-gate → if SAFE: author 0002b → verify → pause → on approval `execute_migration` → contract PR. Verify prod ends at 0002b with `users` lacking the moved columns and `user_profiles` = 200k.

- [ ] **Step 5: Record evidence + commit a rehearsal-script update**

Update `scripts/rehearse_golden.sh` (or a new `scripts/rehearse_phased.sh`) to run the two-phase sequence, and commit it. Capture the live session id + turn ids in the plan's verification blockquote.

```bash
git add scripts/rehearse_phased.sh
git commit -m "test: two-phase expand/contract rehearsal script"
```

---

### Task 8: README zero-downtime claim rewrite

**Files:**
- Modify: `README.md` — replace the zero-downtime claim with the operator protocol + the contract-gate guarantee (through a Qodo-reviewed PR).

**Interfaces:**
- Consumes: all prior tasks.

- [ ] **Step 1: Rewrite the zero-downtime section of `README.md`**

Replace any "zero-downtime" assertion with:

````markdown
## Zero-downtime, by construction

SchemaForge splits every migration into two phases and gates the second on a
deterministic check:

1. **Expand** — an additive migration (new tables/columns/indexes + data
   backfill) applied to the live database now. It removes nothing, so the
   running application keeps serving. SchemaForge validates the migration is
   *expand-only* (`sf-pipeline validate-phase --phase expand`) and rejects any
   destructive verb both at validation and at apply time
   (`execute_migration(phase='expand')`).

2. **Contract** — the destructive cleanup (drop the old columns), applied
   *later*, only after the operator deploys app code that no longer reads them.
   SchemaForge will not propose the contract until the **contract gate** is
   clean: `sf-pipeline contract-gate` runs column-level reverse reachability
   over the impact graph and reports `BLOCKED` with the exact files/lines that
   still read the column. Only when it returns `SAFE` is the contract migration
   authored, verified, and (after human approval) applied.

**Zero-downtime holds when the operator follows: apply expand → deploy the
dual-write app build → verify the contract gate is clean → apply contract.**
The contract cannot be applied while any live code reads the old columns — the
gate is a deterministic, machine-checkable check over the codebase, not a
prompt. A failing statement inside either phase rolls the whole transaction
back; every prod write goes through a single human-approved transaction.

For large tables, `sf-pipeline analyze-locks` flags long-lock DDL (SET NOT
NULL, ALTER TYPE, non-concurrent CREATE INDEX) and names the online
alternative (the CHECK-constraint trick for SET NOT NULL; CREATE INDEX
CONCURRENTLY for indexes — note these cannot run inside the single-transaction
apply and are emitted as a separate step).
````

- [ ] **Step 2: Open the PR and run Qodo**

```bash
git checkout -b docs/zero-downtime-claim
git add README.md
git commit -m "docs: zero-downtime by construction — expand/contract + contract gate"
git push -u origin docs/zero-downtime-claim
gh pr create --title "docs: zero-downtime by construction" --body "Rewrites the zero-downtime claim to the operator protocol + the deterministic contract gate. Implements the architecture from the zero-downtime plan."
# trigger Qodo with /agentic_review on the PR
```
Address any Qodo findings, merge.

---

## Self-Review (run before execution)

**1. Spec coverage.**
- "zero-downtime if we directly use the original database" → Task 4 (expand can't drop) + Task 5 (never contract in the same turn) + Task 2 (gate) + Task 8 (claim). ✓
- expand/contract split → Tasks 1, 6. ✓
- contract permission before cloud migration → Task 5 (ask_user_question + execute_migration destructiveHint) + Task 4. ✓
- "production-ready / arbitrary repo" → Task 5 dual-write contract is repo-agnostic; Task 6 reference is the demo instance. ✓
- lock analysis for large tables → Task 3. ✓
- transitional app code (dual-write) → Task 5 step 6 + Task 6 step 4. ✓

**2. Placeholder scan.** No TBD/TODO. The dual-write models in Task 6 step 4 uses `sa.` and notes the import must be present — flagged, not a placeholder.

**3. Type consistency.** `validate_phase(file_path, phase)`, `impacted_by_columns(g, columns)`, `analyze_locks(file_path) -> list[LockReport]`, `execute_migration(sql, phase=None)` — names consistent across tasks. CLI subcommands `validate-phase`, `contract-gate`, `analyze-locks` — hyphenated consistently. Column node id `col_{_mid(table)}_{_mid(col)}` matches `impact_graph.build`. ✓

**Gaps.** Task 1 step 5 wires `validate-phase` into the CLI only in the prose ("add `cmd_validate_phase`") — make it a concrete step: add `cmd_validate_phase` calling `validate_phase(args.migration, args.phase)` and register the parser before Task 6 step 3 runs it. (Implementer: add this when doing Task 1.)
