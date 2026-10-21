import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
# Unit and API tests never touch a cluster unless a test opts in explicitly.
os.environ.setdefault("ACADEMY_CLUSTER", "off")
