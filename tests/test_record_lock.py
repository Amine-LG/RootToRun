"""scripts/record.py takes the one-recording-at-a-time lock in the recorder's directory and writes its PID there."""
import ast
import sys

from academy import config
from platforms import RECORDER


@RECORDER
def test_cluster_lock_is_taken_and_names_the_process(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RECORDER_DIR", tmp_path)
    tree = ast.parse((config.ROOT / "scripts" / "record.py").read_text(encoding="utf-8"))
    keep = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) and getattr(n, "module", "") != "academy"]
    keep += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "cluster_lock"]
    ns: dict = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "record.py", "exec"), ns)
    f = ns["cluster_lock"]()
    assert (tmp_path / "cluster.lock").read_text(encoding="utf-8").startswith("pid ")
    f.close()
