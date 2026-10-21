"""The tools a learner needs to practise outside the website (content/<lang>/tools.yaml), and which lessons and labs
use which tool. The second part is derived from the commands themselves, so it stays right when content changes:
a tool counts when its name is in command position for the learner's own shell (at the start, after `;`, `&&`, `||`,
`|`, `$(`, `do`, `then`… or after a wrapper such as `sudo`, `timeout 5` or `xargs`). Text in single quotes, the
arguments of `oc exec … --`, `oc debug … --` and `podman run IMAGE …` are not in command position: those programs run
in a container or on a node, not on the learner's machine.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from . import config


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Link(_Strict):
    title: str
    url: str = Field(pattern=r"^https://")


class Tool(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    name: str
    what: str
    commands: list[str] = Field(min_length=1)  # program names that mean this tool is used
    install: list[Link] = Field(min_length=1)  # the tool's own installation or reference documentation
    verify: str  # a command that shows the tool is installed (its version, or its path)
    notes: str = ""


def _file(lang: str | None) -> Path:
    root = config.ROOT / "content"
    p = root / (lang or "en") / "tools.yaml"
    return p if p.exists() else root / "en" / "tools.yaml"


@functools.lru_cache(maxsize=8)
def _load(path: str, mtime: float) -> tuple[Tool, ...]:
    tools = tuple(Tool(**t) for t in yaml.safe_load(Path(path).read_text(encoding="utf-8")) or [])
    ids = [t.id for t in tools]
    names = [c for t in tools for c in t.commands]
    if len(set(ids)) != len(ids) or len(set(names)) != len(names):
        raise ValueError("tools.yaml: a tool id or command name is listed twice")
    return tools


def load(lang: str | None = None) -> list[Tool]:
    p = _file(lang)
    return list(_load(str(p), p.stat().st_mtime))


# where a program name is in command position: start of the line or of a list or pipeline, after a substitution or a
# compound keyword, or after a wrapper that runs the next word as a command; then optional NAME=value assignments
_POSITION = (r"(?:^|[;&|(`{\n]|\$\(|\bdo\b|\bthen\b|\belse\b|\btime\b|!|\bsudo\b|\btimeout\s+\S+"
             r"|\bxargs(?:\s+-\S+)*|\bwatch(?:\s+-\S+(?:\s+\d+)?)*)\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*")


@functools.lru_cache(maxsize=16)
def _programs_rx(names: tuple[str, ...]) -> re.Pattern:
    # one pattern for all names (longest first), with the name in command position captured in a lookahead group, so
    # that a match consumes nothing and every position is tried: the same result as one search per name, in one pass
    alt = "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True))
    return re.compile(r"(?=" + _POSITION + r"(" + alt + r")(?![-\w.=/]))")


def programs(cmd: str, names: list[str]) -> set[str]:
    """The names (from `names`) that the learner's shell would run as programs in `cmd`."""
    text = re.sub(r"'[^']*'", "''", cmd)  # single-quoted text is data for the shell, never a command it runs
    return {m.group(1) for m in _programs_rx(tuple(names)).finditer(text)}


def used(cmds, lang: str | None = None) -> list[str]:
    """Ids of the tools that these commands use, in the order of tools.yaml. Cached by the commands and the tools file
    (it is asked for every lesson and lab on each /api/curriculum request, and matching is the expensive part)."""
    f = _file(lang)
    return list(_used(tuple(c for c in cmds if c), str(f), f.stat().st_mtime if f.exists() else 0.0, lang))


@functools.lru_cache(maxsize=1024)
def _used(cmds: tuple[str, ...], path: str, mtime: float, lang: str | None) -> tuple[str, ...]:
    tools = load(lang)
    names = [c for t in tools for c in t.commands]
    found: set[str] = set()
    for c in cmds:
        found |= programs(c, names)
    return tuple(t.id for t in tools if found & set(t.commands))


def lesson_commands(lesson) -> list[str]:
    """Every command a lesson shows or asks for: its recorded commands, the steps' runs and the accepted answers."""
    out = [c.cmd for c in lesson.commands]
    for st in lesson.flow:
        out.append(getattr(st, "run", None) or "")
        out.extend(getattr(st, "accept", None) or [])
    return out


def lab_commands(lab) -> list[str]:
    """Every command of a lab, incident or challenge that the learner runs (steps, investigation, fix; not the
    grader's own trials)."""
    out = [c.cmd for c in getattr(lab, "commands", None) or []]
    for st in getattr(lab, "steps", None) or []:
        out.extend(c.cmd for c in st.commands)
    for key in ("investigate", "fix"):
        out.extend(c.cmd for c in getattr(lab, key, None) or [])
    return out


def lesson_tools(lesson, lang: str | None = None) -> list[str]:
    """The tools a lesson's commands use. A lesson recorded on the learner's machine whose commands need no listed
    tool still needs a Linux shell: that is what it teaches."""
    found = used(lesson_commands(lesson), lang)
    if not found and lesson.record_on == "host" and any(lesson_commands(lesson)):
        found = ["linux"]
    return found
