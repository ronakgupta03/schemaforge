from pathlib import Path

from schemaforge_core.detect import detect_language, detect_migration_tool


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_detect_ts_drizzle(tmp_path):
    _write(tmp_path, "src/db/schema.ts", "import { pgTable } from 'drizzle-orm';\n")
    _write(tmp_path, "src/server.ts", "export const x = pgTable('x', { id: serial('id') });\n")
    assert detect_language(str(tmp_path)) == "ts"
    assert detect_migration_tool(str(tmp_path)) == "none"


def test_detect_ts_with_migrations_dir(tmp_path):
    _write(tmp_path, "drizzle.config.ts", "export default {}\n")
    _write(tmp_path, "migrations/0001.sql", "CREATE TABLE t (id int);\n")
    _write(tmp_path, "src/schema.ts", "const u = pgTable('u',{id:serial('id')});\n")
    assert detect_migration_tool(str(tmp_path)) == "sql"


def test_detect_python(tmp_path):
    _write(tmp_path, "alembic.ini", "[alembic]\nscript_location = alembic\n")
    _write(tmp_path, "app/models.py", "from sqlalchemy import Column\n")
    assert detect_language(str(tmp_path)) == "python"
    assert detect_migration_tool(str(tmp_path)) == "alembic"


def test_detect_ignores_node_modules(tmp_path):
    # drizzle inside node_modules is a vendored dep, not the app's own code
    _write(tmp_path, "node_modules/drizzle/schema.ts",
           "const u = pgTable('u',{id:serial('id')});\n")
    _write(tmp_path, "app/main.py", "print('hi')\n")
    assert detect_language(str(tmp_path)) == "python"
