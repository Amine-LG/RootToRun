"""The trusted CI router (scripts/ci_needs_site.py --tier): the quick content lane only for a narrow allow-list of
contributor data; code, tests, workflows, the classifier itself and anything unknown get the deep lane."""
import os
import subprocess
import sys

import pytest

from academy import config
from platforms import WINDOWS

sys.path.insert(0, str(config.ROOT / "scripts"))
from ci_needs_site import needs_site, parse_raw, tier  # noqa: E402

SCRIPT = config.ROOT / "scripts" / "ci_needs_site.py"
# the router runs the classifier on ubuntu-latest and reads its exact bytes; Windows prints \r\n
linux_router = pytest.mark.skipif(WINDOWS, reason="the router runs on ubuntu-latest")


def run_tier(raw: bytes, script=SCRIPT) -> str:
    return subprocess.run([sys.executable, "-I", str(script), "--tier"], input=raw, capture_output=True,
                          check=True).stdout.decode()


def test_only_explicit_contributor_data_gets_the_content_lane():
    for path in ["content/en/lessons/o1-flow.yaml", "content/fr/labs/a.yml", "content/LICENSE.md",
                 "content/recordings/en/lesson.json", "content/media/o1-flow/console.png", "docs/AUTHORING.md",
                 "docs/sub/dir/x.md", "README.md", "CONTRIBUTING.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md",
                 # odd but harmless names: data never reaches a shell or a workflow expression
                 "docs/a space.md", "docs/$(touch PWNED).md", "docs/a\nb.md", "docs/-option.md", "docs/`id`.md"]:
        assert tier([path]) == "content", repr(path)
    assert tier(["content/en/lessons/a.yaml", "docs/WINDOWS.md", "content/media/a/b.png"]) == "content"


def test_code_tests_workflows_and_unknown_paths_get_the_deep_lane():
    for path in ["frontend/src/App.tsx", "frontend/package.json", "frontend/package-lock.json", "backend/academy/main.py",
                 "scripts/ci_needs_site.py", "scripts/test_content.sh", "tests/test_accounts.py", "tests/e2e/conftest.py",
                 "deploy/nginx/nginx.conf", "Containerfile", ".dockerignore", ".gitattributes", "pytest.ini",
                 ".github/workflows/ci.yml", ".github/workflows/checks-content.yml", ".github/actions/python-env/action.yml",
                 ".github/ISSUE_TEMPLATE/a.yml", ".github/CODEOWNERS", "requirements.txt", "requirements-dev.txt",
                 "LICENSE", "NOTICE", "compose.yaml", "run.sh", "unknown", "docs", "README.md.bak", "readme.md",
                 "contentx/a.yaml", " content/en/a.yaml", "content", "content/tool.py", "content/hook.sh",
                 "content/en/a.json", "content/en/a.YAML", "content/media/a/evil.svg", "content/media/a/big.jpg",
                 "content/media/x.png", "content/media/a/b/c.png", "content/recordings", "docs/tool.py", "docs/a.MD",
                 "docs/shot.png", "/docs/a.md", "docs/../scripts/a.md", "docs//a.md", "docs/./a.md", "docs/a\\b.md", ""]:
        assert tier(["content/en/lessons/a.yaml", path]) == "deep", repr(path)
    assert tier([]) == "deep"


@linux_router
def test_the_command_line_reads_git_nul_lists_and_fails_closed():
    assert run_tier(b"docs/$(touch PWNED).md\0docs/a\nb.md\0docs/-a.md\0") == "tier=content\n"
    for raw in [b"docs/a.md\0tests/a.py\0",   # one code path
                b"docs/a.md\nbackend/a.py\0",  # newline-separated (not git -z): one odd name, not a docs file
                b"docs/a.md\n",                # truncated: no final NUL
                b"", b"\0"]:
        assert run_tier(raw) == "tier=deep\n", raw
    bad = subprocess.run([sys.executable, "-I", str(SCRIPT), "--outputs"], input=b"docs/a.md\0", capture_output=True)
    assert bad.returncode != 0 and b"tier=" not in bad.stdout


@linux_router
def test_git_deletions_renames_and_a_pull_request_that_edits_the_classifier(tmp_path):
    """What the router does: the BASE blob of the classifier, executed with isolated Python, on git's own list."""
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path)
    git("init", "-q")
    git("config", "user.email", "test@example.org")
    git("config", "user.name", "CI test")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/ci_needs_site.py").write_bytes(SCRIPT.read_bytes())
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/a.md").write_text("data", encoding="utf-8")
    (tmp_path / "app.py").write_text("code", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD").decode().strip()
    trusted = tmp_path.parent / "base-classifier.py"
    trusted.write_bytes(git("show", f"{base}:scripts/ci_needs_site.py"))

    def lane():
        raw = git("diff", "--no-renames", "--raw", "-z", f"{base}...HEAD")
        return subprocess.check_output([sys.executable, "-I", str(trusted), "--tier-raw"], input=raw).decode()

    (tmp_path / "docs/a.md").unlink()
    git("add", "-u")
    git("commit", "-qm", "delete a doc")
    assert lane() == "tier=content\n"
    git("mv", "app.py", "docs/renamed.md")
    git("commit", "-qm", "rename code into docs")
    assert lane() == "tier=deep\n"  # the old path counts: code cannot be renamed into an allowed name
    git("reset", "-q", "--hard", base)
    (tmp_path / "scripts/ci_needs_site.py").write_text('print("tier=content")\n', encoding="utf-8")
    (tmp_path / "docs/b.md").write_text("only a doc, says the edited classifier", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "classifier that claims the content lane")
    head_copy = tmp_path / "scripts/ci_needs_site.py"
    assert run_tier(b"scripts/ci_needs_site.py\0", head_copy) == "tier=content\n"  # what the PR's copy would say
    assert lane() == "tier=deep\n"  # what the base copy says: the router never runs the PR's copy


@linux_router
def test_git_file_modes_cannot_disguise_code_as_content(tmp_path):
    """Exercise git's actual raw format, including executable data, symlinks, gitlinks and deletion of each."""
    def git(*args, data=None):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], input=data)
    git("init", "-q")
    git("config", "user.email", "test@example.org")
    git("config", "user.name", "CI test")
    git("commit", "--allow-empty", "-qm", "base")
    base = git("rev-parse", "HEAD").decode().strip()
    blob = git("hash-object", "-w", "--stdin", data=b"data\n").decode().strip()
    for mode in ("100644", "100755", "120000", "160000"):
        path = f"docs/{mode}-é.md"
        git("update-index", "--add", "--cacheinfo", mode, base if mode == "160000" else blob, path)
        git("commit", "-qm", f"add {mode}")
        raw = git("diff", "--no-renames", "--raw", "-z", "HEAD^...HEAD")
        assert tier(parse_raw(raw)) == ("content" if mode == "100644" else "deep")
        reverse = git("diff", "--no-renames", "--raw", "-z", "HEAD", "HEAD^")
        assert tier(parse_raw(reverse)) == ("content" if mode == "100644" else "deep")
        assert subprocess.check_output([sys.executable, "-I", str(SCRIPT), "--tier-raw"], input=raw).decode() == (
            "tier=content\n" if mode == "100644" else "tier=deep\n")
    for raw in (b"", b"\0", b":100644 100644 abcd abcd M\0docs/a.md", b"docs/a.md\0",
                b":100644 100644 abcd abcd R100\0docs/a.md\0docs/b.md\0"):
        assert tier(parse_raw(raw)) == "deep"
    assert tier(parse_raw(b":100644 100644 abcd abcd M\0docs/a\nb.md\0")) == "content"


def test_the_old_interface_is_unchanged_for_the_rollout():
    """The old ci.yml (still on main until the lanes are merged) pipes newline-separated paths and reads true/false."""
    assert not needs_site(["docs/AUTHORING.md", "README.md", ".github/ISSUE_TEMPLATE/content-problem.yml"])
    assert not needs_site(["tests/test_issue_forms.py", "CONTRIBUTING.md"])
    for path in ["content/en/lessons/o1-flow.yaml", "frontend/src/pages/Lesson.tsx", "Containerfile",
                 ".github/workflows/ci.yml", "tests/e2e/conftest.py", "some/new/file.txt"]:
        assert needs_site(["docs/AUTHORING.md", path]), path
    assert needs_site([]) and needs_site(["", "  "])
    out = subprocess.run([sys.executable, str(SCRIPT)], input="docs/INSTALL.md\nSECURITY.md\n", capture_output=True,
                         text=True, encoding="utf-8", check=True, env={**os.environ}).stdout
    assert out == "false\n"

