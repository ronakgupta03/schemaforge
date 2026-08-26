from pathlib import Path

from schemaforge_core.pipeline import _load_queries


def test_load_queries(tmp_path: Path):
    f = tmp_path / "bench.sql"
    f.write_text(
        "-- name: a\nSELECT 1;\n\n-- name: b\nSELECT 2;\n"
    )
    q = _load_queries(f)
    assert q == [("a", "SELECT 1;"), ("b", "SELECT 2;")]
