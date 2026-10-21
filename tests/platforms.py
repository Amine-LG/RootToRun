"""What does not exist on Windows (docs/WINDOWS.md, "What stays Linux-only"): the tests that need it say so."""
import stat
import sys

import pytest

WINDOWS = sys.platform == "win32"
# the recorder runs lessons in bash, in process groups, with file locks and executable wrapper scripts
RECORDER = pytest.mark.skipif(WINDOWS, reason="recording lessons is Linux-only (bash, process groups, flock)")


def assert_owner_only(path):
    """Mode 600 where files have Unix permission bits. Windows has none (a file there takes the access rules of its
    folder, the user's own profile for Root to Run's data), so there is nothing to check."""
    if not WINDOWS:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path
