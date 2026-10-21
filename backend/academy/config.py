"""Configuration. Everything is overridable with environment variables; nothing assumes a user or a path.

ACADEMY_CLUSTER        "auto" (default): offer cluster features when `oc` exists;
                       "off": public/practice mode, no cluster access at all (recorded outputs only).
ACADEMY_API_SERVER     API URL used to log in (default: CRC's https://api.crc.testing:6443).
ACADEMY_CRC_HOME       CRC home (default ~/.crc), used only to find CRC's generated passwords and CA.
ACADEMY_KUBECONFIG_LEARNER / _READER / _ADMIN
                       Optional: use an existing kubeconfig for an identity instead of logging in
                       (any OpenShift or Kubernetes cluster). Copied into the private data directory.
ACADEMY_DATA_DIR       private runtime data (kubeconfigs, lab files); default ./data
ACADEMY_DIST_DIR       built frontend to serve (default ./frontend/dist)
ACADEMY_LANG           default content language (default en)
ACADEMY_ALLOWED_HOSTS  extra Host header values accepted, comma separated. "*" accepts any host and is only
                       allowed together with ACADEMY_CLUSTER=off (a server that can reach a cluster must stay
                       bound to localhost names).
ACADEMY_REPO_URL       The project's public GitHub repository (e.g. https://github.com/owner/name). Empty (default):
                       lesson pages show no "Report an issue" / "Edit this lesson" actions.
ACADEMY_REPO_BRANCH    Branch used for "Edit this lesson" links (default main).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTENT_ROOT = Path(os.environ.get("ACADEMY_CONTENT_DIR", ROOT / "content"))
RECORDINGS_DIR = CONTENT_ROOT / "recordings"
DATA_DIR = Path(os.environ.get("ACADEMY_DATA_DIR", ROOT / "data"))
KUBE_DIR = DATA_DIR / "kube"
# the recorder's own files (full experiment records, failed recordings, the cluster lock), never committed
RECORDER_DIR = Path(os.environ.get("ACADEMY_PRIVATE_DIR", DATA_DIR / "recorder"))
LABFILES_DIR = DATA_DIR / "labfiles"
DIST_DIR = Path(os.environ.get("ACADEMY_DIST_DIR", ROOT / "frontend" / "dist"))
DEFAULT_LANG = os.environ.get("ACADEMY_LANG", "en")
# English is the source language. Another language is a directory content/<lang>/ (e.g. fr, pt-BR) holding
# translated items only: anything it does not translate falls back to English.
LANGS = ("en", *sorted(d.name for d in CONTENT_ROOT.iterdir()
                       if d.is_dir() and d.name != "en" and __import__("re").fullmatch(r"[a-z]{2}(-[A-Z]{2})?", d.name)))

REPO_URL = os.environ.get("ACADEMY_REPO_URL", "").strip().rstrip("/")
REPO_BRANCH = os.environ.get("ACADEMY_REPO_BRANCH", "main").strip() or "main"

CLUSTER_MODE = os.environ.get("ACADEMY_CLUSTER", "auto")  # auto | off
CRC_HOME = Path(os.environ.get("ACADEMY_CRC_HOME", Path.home() / ".crc"))
CRC_MACHINE = CRC_HOME / "machines" / "crc"
API_SERVER = os.environ.get("ACADEMY_API_SERVER", "https://api.crc.testing:6443")
EXTERNAL_KUBECONFIG = {i: os.environ.get(f"ACADEMY_KUBECONFIG_{i.upper()}") for i in ("learner", "reader", "admin")}

# Everything the academy may create, mutate or delete lives in projects named academy-<x>, created by
# the learner identity with this description. Nothing else is ever deleted.
NS_PREFIX = "academy-"
SYSTEM_NS = "academy-system"
MARKER = "Managed by Root to Run"
# the description of projects created before the project had its final name: still the academy's own
MARKERS = (MARKER, "Managed by OpenShift Engineering Academy")

OC_TIMEOUT_S = int(os.environ.get("ACADEMY_OC_TIMEOUT", "30"))


def content_dir(lang: str | None = None) -> Path:
    lang = lang if lang in LANGS else DEFAULT_LANG
    return CONTENT_ROOT / lang


def cluster_enabled() -> bool:
    return CLUSTER_MODE != "off" and oc_path() is not None


def oc_path() -> str | None:
    if CLUSTER_MODE == "off":
        return None
    found = shutil.which("oc")
    if found:
        return found
    crc_oc = CRC_HOME / "bin" / "oc" / "oc"
    return str(crc_oc) if crc_oc.exists() else None


def helm_path() -> str | None:
    return None if CLUSTER_MODE == "off" else shutil.which("helm")


def crc_path() -> str | None:
    if CLUSTER_MODE == "off":
        return None
    found = shutil.which("crc")
    if found:
        return found
    p = CRC_HOME / "bin" / "crc"
    return str(p) if p.exists() else None

# the product name: frontend/product.json (shared with the frontend); ACADEMY_SITE_NAME overrides it for the server only
_PRODUCT = ROOT / "frontend" / "product.json"
SITE_NAME = os.environ.get("ACADEMY_SITE_NAME") or (json.loads(_PRODUCT.read_text(encoding="utf-8"))["name"] if _PRODUCT.exists() else "Learning lab")
SITE_DESCRIPTION = json.loads(_PRODUCT.read_text(encoding="utf-8")).get("description", "") if _PRODUCT.exists() else ""
