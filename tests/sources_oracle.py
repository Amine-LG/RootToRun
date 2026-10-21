"""Where a page's content is defined, found independently of the code that builds the Edit links: the YAML file whose
data defines an id (read with a YAML parser), and the component file each model's catalogue entry imports
(frontend/src/sims/index.ts). Shared by tests/test_contribute_sources.py and tests/e2e/test_contribute_everywhere.py."""
import re

import yaml

from academy import config

EN = config.ROOT / "content" / "en"
SIMS_INDEX = config.ROOT / "frontend" / "src" / "sims" / "index.ts"
# `import X from './X'` with either quote and an optional semicolon (a formatting choice, not a different import)
IMPORT = re.compile(r"""^\s*import\s+(\w+)\s+from\s+(['"])\./([\w-]+)\2\s*;?\s*$""", re.M)
ENTRY = re.compile(r"""\bid:\s*(['"])([\w-]+)\1\s*,[\s\S]*?\bComponent:\s*(\w+)\b""")


def defined_in(sub: str, ident: str, key: str = "id") -> str:
    """The content file (relative to the repository) whose YAML defines `ident`."""
    for f in sorted((EN / sub).glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        if any(isinstance(item, dict) and item.get(key) == ident for item in (data if isinstance(data, list) else [data])):
            return f.relative_to(config.ROOT).as_posix()
    raise AssertionError(f"{ident} is not defined in content/en/{sub}")


def model_files() -> dict[str, str]:
    """Model id -> the component file its catalogue entry imports, e.g. scheduler -> frontend/src/sims/SchedulerSim.tsx."""
    index = SIMS_INDEX.read_text(encoding="utf-8")
    files = {name: path for name, _, path in IMPORT.findall(index)}
    return {model: f"frontend/src/sims/{files[component]}.tsx" for _, model, component in ENTRY.findall(index)}
