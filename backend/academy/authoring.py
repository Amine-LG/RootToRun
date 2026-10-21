"""Opt-in local authoring over the existing YAML. No Git or cluster operations."""
from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import secrets
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

from . import config, curriculum, labs

MODELS = {"lesson": curriculum.Lesson, "module": curriculum.Module, "track": curriculum.Track,
          "route": curriculum.Route, "diagnostic": curriculum.Diagnostic}
COLLECTIONS = {kind: kind + "s" for kind in MODELS}
IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,159}$")
_LOCK = threading.RLock()


def start(app):
    """Called once during server startup; the secret is never part of metadata."""
    app.state.authoring = os.environ.get("ACADEMY_AUTHORING") == "1"
    app.state.author_token = None
    if app.state.authoring:
        app.state.author_token = os.environ.get("ACADEMY_AUTHORING_TOKEN") or secrets.token_urlsafe(32)
        port = os.environ.get("ACADEMY_PORT", "8768")
        if "--port" in sys.argv:
            port = sys.argv[sys.argv.index("--port") + 1]
        print(f"Local authoring: http://127.0.0.1:{port}/author#token={quote(app.state.author_token, safe='')}", flush=True)


def require_author(request: Request):
    if not getattr(request.app.state, "authoring", False):
        raise HTTPException(404, "authoring is off")
    try:
        local = ipaddress.ip_address(request.client.host).is_loopback if request.client else False
    except ValueError:
        local = False
    if not local:
        raise HTTPException(403, "authoring requires a loopback client")
    supplied = request.headers.get("authorization", "")
    expected = "Bearer " + request.app.state.author_token
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "author token required", headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix="/api/author", dependencies=[Depends(require_author)])


class Edit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    id: str
    yaml: str = Field(max_length=1_000_000)


class Draft(Edit):
    base_hash: str | None = None


class Publish(Edit):
    base_hash: str


class Create(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    file: str
    yaml: str = Field(max_length=1_000_000)


class Rollback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    id: str
    revision: str
    base_hash: str | None = None  # UI supplies its loaded file hash; API callers may restore the current file


def identity(kind, ident=None):
    if kind not in MODELS:
        raise HTTPException(400, "unknown content kind")
    if ident is not None and not IDENTIFIER.fullmatch(ident):
        raise HTTPException(400, "invalid item id")


def safe_path(root: Path, relative: str) -> Path:
    """Only normal relative paths; refuse symlinks, including intermediate directories."""
    rel = Path(relative)
    if rel.is_absolute() or any(p in ("..", ".") for p in rel.parts) or not rel.parts:
        raise HTTPException(400, "invalid relative path")
    root = root.resolve()
    path = root
    for part in rel.parts:
        path = path / part
        if path.is_symlink():
            raise HTTPException(400, "symlinks are not editable")
    if not path.resolve().is_relative_to(root):
        raise HTTPException(400, "path is outside content")
    return path


class SourceLoader(curriculum._LOADER):
    """Safe YAML without duplicate keys or aliases (blocks must stand alone)."""
    def __init__(self, stream):
        self.source = stream
        super().__init__(stream)

    def get_single_data(self):
        if any(isinstance(token, yaml.AliasToken) for token in yaml.scan(self.source, Loader=curriculum._LOADER)):
            raise ValueError("YAML aliases are not supported in authoring")
        return super().get_single_data()

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(k, deep=deep) for k, _ in node.value]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate YAML keys")
        return super().construct_mapping(node, deep=deep)


def parse(source, kind):
    raw = yaml.load(source, Loader=SourceLoader)
    if kind != "diagnostic":
        if not isinstance(raw, list) or len(raw) != 1:
            raise ValueError("provide exactly one YAML list item (starting with '- ')")
        node = yaml.compose(source, Loader=SourceLoader)
        if node.flow_style:
            raise ValueError("provide a block-style YAML list item (starting with '- ')")
        raw = raw[0]
    return MODELS[kind].model_validate(raw)


def item_id(obj):
    return obj.track if isinstance(obj, curriculum.Diagnostic) else obj.id


@dataclass
class Block:
    kind: str
    id: str
    title: str
    path: Path
    text: str
    start: int
    end: int

    @property
    def source(self):
        return self.text[self.start:self.end]

    def response(self):
        return {"kind": self.kind, "id": self.id, "title": self.title,
                "file": self.path.relative_to(config.CONTENT_ROOT.resolve()).as_posix(),
                "yaml": self.source, "hash": digest(self.text)}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scalar_end(node):
    if isinstance(node, ScalarNode):
        return node.end_mark.index
    children = node.value if isinstance(node, SequenceNode) else [n for pair in node.value for n in pair]
    return max([node.start_mark.index, *(scalar_end(n) for n in children),
                node.end_mark.index if node.flow_style else 0])


def blocks(kind):
    identity(kind)
    root = config.content_dir()
    relative = root.relative_to(config.CONTENT_ROOT).as_posix()
    sub = COLLECTIONS[kind]
    paths = sorted((root / sub).glob("*.yaml")) if kind in ("lesson", "diagnostic") else [root / f"{sub}.yaml"]
    out = []
    for candidate in paths:
        path = safe_path(config.CONTENT_ROOT, f"{relative}/{candidate.relative_to(root).as_posix()}")
        if not path.exists():
            continue
        text = path.read_bytes().decode("utf-8")  # retain CRLF, Unicode and every unrelated byte
        try:
            raw = yaml.load(text, Loader=SourceLoader)
            node = yaml.compose(text, Loader=SourceLoader)
            if kind == "diagnostic":
                if not isinstance(raw, dict):
                    raise ValueError("expected one diagnostic object")
                out.append(Block(kind, raw["track"], raw.get("title", raw["track"]), path, text, 0, len(text)))
                continue
            if not isinstance(node, SequenceNode) or node.flow_style:
                raise ValueError("expected a block-style YAML list")
            for data, entry in zip(raw, node.value):
                if not isinstance(entry, MappingNode):
                    raise ValueError("expected block-style list objects")
                start = text.rfind("\n", 0, entry.start_mark.index) + 1
                if not text[start:entry.start_mark.index].strip().startswith("-"):
                    raise ValueError("each item must start on its own line")
                end = scalar_end(entry)
                # Include the final scalar's inline comment and newline; leave standalone comments alone.
                if end and text[end - 1] != "\n":
                    line_end = text.find("\n", end)
                    end = len(text) if line_end < 0 else line_end + 1
                out.append(Block(kind, data["id"], data.get("title", data["id"]), path, text, start, end))
        except (ValueError, KeyError, TypeError, yaml.YAMLError) as e:
            raise HTTPException(422, f"{candidate.name}: {e}") from None
    ids = [b.id for b in out]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, f"duplicate {kind} ids")
    return out


def find(kind, ident):
    identity(kind, ident)
    found = [b for b in blocks(kind) if b.id == ident]
    if not found:
        raise HTTPException(404, "item not found")
    return found[0]


def whole_problems():
    curriculum._cache.clear()
    return curriculum.load()["errors"] + labs.errors() + curriculum.integrity(set(labs.load()))


def check(body: Edit, *, creating=False):
    identity(body.kind, body.id)
    errors, warnings = [], []
    obj = None
    try:
        obj = parse(body.yaml, body.kind)
        if item_id(obj) != body.id:
            raise ValueError("item identity cannot change")
        old = None if creating else parse(find(body.kind, body.id).source, body.kind)
        if isinstance(old, curriculum.Lesson):
            removed = {s.id for s in old.sections} - {s.id for s in obj.sections}
            if removed:
                errors.append("Existing section ids cannot be removed or renamed: " + ", ".join(sorted(removed)))
            previous = [p.id for p in old.predict]
            current = [p.id for p in obj.predict]
            # positional answers from the first version are migrated only onto long-form lessons, where order matters
            if not obj.flow and any(q in current and current.index(q) != i for i, q in enumerate(previous)):
                errors.append("Existing questions cannot be reordered; append new questions at the end.")
            gone = {st.id for st in old.flow} - {st.id for st in obj.flow}
            if gone and obj.flow:
                warnings.append("Flow steps removed or renamed: practice results saved for them will no longer show: " + ", ".join(sorted(gone)))
            if set(previous) - set(current):
                warnings.append("Question prompts changed or were removed: saved answers will not carry over for those questions.")
        curriculum._cache.clear()
        data = curriculum.load()
        candidate = {**data, COLLECTIONS[body.kind]: {**data[COLLECTIONS[body.kind]], body.id: obj}}
        errors.extend(data["errors"])
        errors.extend(labs.errors())
        errors.extend(curriculum.integrity(set(labs.load()), data=candidate))
        if isinstance(obj, curriculum.Lesson) and obj.flow:
            from . import teachlint

            unrecorded, advice = teachlint.lint(candidate, obj)
            warnings.extend(e.replace(" has no recording", " is not recorded yet") for e in unrecorded)
            warnings.extend("Teaching standard: " + w for w in advice)
    except (ValueError, TypeError, yaml.YAMLError) as e:
        errors.append(str(e))
    return {"ok": not errors, "errors": errors, "warnings": warnings}, obj


def storage(relative):
    return safe_path(config.DATA_DIR, "authoring/" + relative)


def atomic_write(path, data: bytes, *, private=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".author-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600 if private or not path.exists() else path.stat().st_mode & 0o777)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + secrets.token_hex(4)


def replace_checked(path, before, after):
    # Recheck immediately before replacing. API writes are serialised by _LOCK.
    if path.exists() and path.read_bytes() != before:
        raise HTTPException(409, "file changed; reload before publishing")
    existed = path.exists()
    atomic_write(path, after)
    try:
        problems = whole_problems()
        if problems:
            raise HTTPException(422, {"ok": False, "errors": problems, "warnings": []})
    except Exception:
        if existed:
            atomic_write(path, before)
        else:
            path.unlink()
        curriculum._cache.clear()
        raise


def publish_edit(body: Publish):
    with _LOCK:
        block = find(body.kind, body.id)
        if body.base_hash != digest(block.text):
            raise HTTPException(409, "file changed; reload before publishing")
        result, _ = check(body)
        if not result["ok"]:
            raise HTTPException(422, result)
        source = body.yaml
        suffix = block.text[block.end:]
        if suffix and not suffix.startswith(("\n", "\r")) and not source.endswith("\n"):
            source += "\r\n" if "\r\n" in block.text else "\n"
        revision = stamp() + ".yaml"
        revision_path = storage(f"revisions/{body.kind}/{body.id}/{revision}")
        atomic_write(revision_path, block.source.encode(), private=True)
        try:
            replace_checked(block.path, block.text.encode(), (block.text[:block.start] + source + block.text[block.end:]).encode())
        except Exception:
            revision_path.unlink()
            raise
        return {**find(body.kind, body.id).response(), "warnings": result["warnings"], "revision": revision}


@router.get("/index")
def index():
    return [{k: v for k, v in b.response().items() if k in ("kind", "id", "title", "file")}
            for kind in MODELS for b in blocks(kind)]


@router.get("/item/{kind}/{ident}")
def get_item(kind: str, ident: str):
    return find(kind, ident).response()


@router.post("/validate")
def validate(body: Edit):
    with _LOCK:
        return check(body)[0]


@router.post("/preview")
def preview(body: Edit):
    with _LOCK:
        result, obj = check(body)
        if not result["ok"]:
            raise HTTPException(422, result)
        if body.kind != "lesson":
            raise HTTPException(400, "preview is available for lessons")
        from .main import lesson_payload
        return lesson_payload(obj)


@router.post("/draft")
def save_draft(body: Draft):
    identity(body.kind, body.id)
    with _LOCK:
        block = find(body.kind, body.id)
        import json
        path = storage(f"drafts/{body.kind}/{body.id}.json")
        data = {**body.model_dump(), "base_hash": body.base_hash or digest(block.text), "file": block.response()["file"], "saved_at": stamp()}
        atomic_write(path, json.dumps(data).encode(), private=True)
        return {"ok": True, "saved_at": data["saved_at"]}


@router.get("/drafts")
@router.get("/draft")
def drafts():
    import json
    directory = storage("drafts")
    return [json.loads(safe_path(directory, p.relative_to(directory).as_posix()).read_bytes())
            for p in sorted(directory.glob("*/*.json"))]


@router.post("/publish")
def publish(body: Publish):
    return publish_edit(body)


@router.get("/revisions/{kind}/{ident}")
def revisions(kind: str, ident: str):
    find(kind, ident)
    directory = storage(f"revisions/{kind}/{ident}")
    return [{"revision": p.name, "yaml": safe_path(directory, p.name).read_bytes().decode()}
            for p in sorted(directory.glob("*.yaml"), reverse=True)]


@router.post("/rollback")
def rollback(body: Rollback):
    find(body.kind, body.id)
    if not re.fullmatch(r"\d{8}T\d{6}\.\d{6}Z-[a-f0-9]{8}\.yaml", body.revision):
        raise HTTPException(400, "invalid revision")
    path = storage(f"revisions/{body.kind}/{body.id}/{body.revision}")
    if not path.is_file():
        raise HTTPException(404, "revision not found")
    return publish_edit(Publish(kind=body.kind, id=body.id, yaml=path.read_bytes().decode(), base_hash=body.base_hash or digest(find(body.kind, body.id).text)))


@router.post("/create")
def create(body: Create):
    identity(body.kind)
    if body.kind not in ("lesson", "diagnostic"):
        raise HTTPException(400, "create supports lessons and diagnostics")
    with _LOCK:
        try:
            obj = parse(body.yaml, body.kind)
        except (ValueError, TypeError, yaml.YAMLError) as e:
            raise HTTPException(422, str(e)) from None
        ident = item_id(obj)
        identity(body.kind, ident)
        if any(b.id == ident for b in blocks(body.kind)):
            raise HTTPException(409, "item already exists")
        expected = f"{config.DEFAULT_LANG}/{COLLECTIONS[body.kind]}/"
        if not body.file.startswith(expected) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*\.yaml", body.file[len(expected):]):
            raise HTTPException(400, "choose a YAML file in the content kind's directory")
        path = safe_path(config.CONTENT_ROOT, body.file)
        if body.kind == "diagnostic" and path.exists():
            raise HTTPException(409, "diagnostic file already exists")
        if body.kind == "lesson" and not path.is_file():
            raise HTTPException(400, "choose an existing lesson file")
        edit = Edit(kind=body.kind, id=ident, yaml=body.yaml)
        result, _ = check(edit, creating=True)
        if not result["ok"]:
            raise HTTPException(422, result)
        before = path.read_bytes() if path.exists() else b""
        source = body.yaml.encode()
        after = before + (b"\n" if before and not before.endswith(b"\n") else b"") + source + (b"" if source.endswith(b"\n") else b"\n")
        replace_checked(path, before, after)
        return find(body.kind, ident).response()
