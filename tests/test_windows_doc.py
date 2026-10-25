"""docs/WINDOWS.md says its commands are tested in CI: every command of its setup, website and test blocks must be one
the Windows jobs of checks-app.yml run (the same executable, script and arguments; CI may add -q, workers or a
shard)."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TESTED_SECTIONS = ("## Get the code and its environment", "## Run the website locally", "## Run the tests")
CI_ONLY = re.compile(r"\s(-q|-n \(\[Math\]::Min\(\[Environment\]::ProcessorCount, 4\)\)|--shard (\d/\d|\$env:SHARD))(?=\s|$)")


def commands(text):
    out = []
    for part in re.split(r"&&|;|\n", text):
        part = re.sub(r"\s+#.*$", "", part).strip()
        if part and not part.startswith(("cd ", "git clone", "$", "try", "}", "foreach", "if ", "\"")):
            out.append(CI_ONLY.sub("", " " + part).strip())
    return out


def test_the_windows_guide_shows_the_commands_ci_runs():
    guide = (ROOT / "docs" / "WINDOWS.md").read_text(encoding="utf-8")
    documented = []
    for section in guide.split("\n## ")[1:]:
        if ("## " + section).startswith(TESTED_SECTIONS):
            for block in re.findall(r"```powershell\n(.*?)```", section, re.S):
                documented += commands(block)
    assert len(documented) >= 12
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "checks-app.yml").read_text(encoding="utf-8"))["jobs"]
    run = []
    for step in jobs["windows"]["steps"] + jobs["windows-python"]["steps"] + jobs["windows-browser"]["steps"]:
        run += commands(step.get("run", ""))
        if "serve.py" in step.get("run", ""):  # the server check starts it with Start-Process: its own form
            run.append(r".venv\Scripts\python.exe scripts\serve.py --practice")
    assert [c for c in documented if c not in run] == []
