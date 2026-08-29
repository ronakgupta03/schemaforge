"""Pipeline dispatch tests: cmd_facts / validate-phase / analyze-locks route to
the python or TS / SQL code paths by language / file extension."""
import json
import sys
from pathlib import Path

from schemaforge_core.pipeline import main

FIX = Path(__file__).parent / "fixtures" / "ts_app"


def test_cmd_facts_dispatches_ts(tmp_path):
    out = tmp_path / "code.json"
    sys.argv = ["sf-pipeline", "facts", "--app", str(FIX), "--out", str(out)]
    main()
    data = json.loads(out.read_text())
    assert any(m["table"] == "posts" for m in data["models"])
    assert any(e["path"] == "/api/posts" for e in data["endpoints"])


def test_cmd_facts_lang_python_still_works(tmp_path):
    # the demo-app is python + sqlalchemy; explicit --lang python must still
    # route to the python extractor (no regression).
    demo = Path(__file__).parent.parent / "demo-app"
    out = tmp_path / "code.json"
    sys.argv = ["sf-pipeline", "facts", "--app", str(demo),
                "--out", str(out), "--lang", "python"]
    if demo.is_dir():
        main()
        data = json.loads(out.read_text())
        assert any(m["table"] == "users" for m in data["models"])
