"""The CI may skip the image and browser tests only for changes that cannot affect the site (scripts/ci_needs_site.py)."""
import subprocess
import sys

from academy import config

sys.path.insert(0, str(config.ROOT / "scripts"))
from ci_needs_site import needs_site  # noqa: E402


def test_documentation_forms_and_python_tests_alone_skip_the_browser_tests():
    assert not needs_site(["docs/AUTHORING.md", "README.md", ".github/ISSUE_TEMPLATE/content-problem.yml"])
    assert not needs_site(["tests/test_issue_forms.py", "CONTRIBUTING.md"])


def test_anything_the_site_is_made_from_needs_them():
    for path in ["content/en/lessons/o1-flow.yaml", "frontend/src/pages/Lesson.tsx", "backend/academy/main.py",
                 "deploy/nginx/nginx.conf", "Containerfile", ".dockerignore", "LICENSE", "NOTICE", "requirements.txt",
                 "requirements-dev.txt", "scripts/export_static.py", "scripts/smoke_image.sh",
                 ".github/workflows/ci.yml", "tests/e2e/test_static_site.py", "tests/e2e/conftest.py"]:
        assert needs_site(["docs/AUTHORING.md", path]), path


def test_unknown_or_missing_input_runs_everything():
    assert needs_site([])
    assert needs_site(["", "  "])
    assert needs_site(["some/new/file.txt"])
    assert needs_site(["docs"])  # not a file under docs/
    assert needs_site(["README.md.bak"])


def test_the_command_line_reads_paths_from_standard_input():
    script = config.ROOT / "scripts" / "ci_needs_site.py"
    run = lambda text: subprocess.run([sys.executable, str(script)], input=text, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
    assert run("docs/INSTALL.md\nSECURITY.md\n") == "false"
    assert run("docs/INSTALL.md\ncontent/en/tracks.yaml\n") == "true"
    assert run("") == "true"
