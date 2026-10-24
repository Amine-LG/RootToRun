import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
# Unit and API tests never touch a cluster unless a test opts in explicitly.
os.environ.setdefault("ACADEMY_CLUSTER", "off")


# The CI runs the Python suite and the browser suite in parallel parts (docs/CI.md).
def pytest_addoption(parser):
    parser.addoption("--shard", default=None, metavar="I/N",
                     help="run only the I-th of N parts of the tests (1-based; every test is in exactly one part)")


def pytest_collection_modifyitems(config, items):
    """--shard I/N keeps every N-th test, starting with the I-th, in collection order: the CI runs the N parts in
    parallel jobs. Parametrised groups of a long test are spread over the parts."""
    shard = config.getoption("--shard")
    if not shard:
        return
    try:
        i, n = (int(x) for x in shard.split("/"))
    except ValueError:
        raise pytest.UsageError(f"--shard {shard}: expected I/N, for example 2/3") from None
    if not 1 <= i <= n:
        raise pytest.UsageError(f"--shard {shard}: I must be between 1 and N")
    keep = [t for k, t in enumerate(items) if k % n == i - 1]
    config.hook.pytest_deselected(items=[t for k, t in enumerate(items) if k % n != i - 1])
    items[:] = keep
