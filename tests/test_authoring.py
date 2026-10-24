"""Authoring tests use copied content and isolated runtime storage; never the real course files."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from academy import authoring, config, curriculum, main
from platforms import assert_owner_only

H = {"Authorization": "Bearer test-author-token", "X-Academy": "1"}


@pytest.fixture
def local(tmp_path, monkeypatch):
    source = tmp_path / "content"
    shutil.copytree(config.CONTENT_ROOT, source)
    use_longform_fixture(source)
    monkeypatch.setattr(config, "CONTENT_ROOT", source)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "RECORDINGS_DIR", source / "recordings")
    monkeypatch.setenv("ACADEMY_AUTHORING", "1")
    monkeypatch.setenv("ACADEMY_AUTHORING_TOKEN", "test-author-token")
    curriculum._cache.clear()
    with TestClient(main.app, client=("127.0.0.1", 12345)) as client:
        yield client
    curriculum._cache.clear()
    main.app.state.authoring = False
    main.app.state.author_token = None


LONGFORM = Path(__file__).parent / "fixtures" / "longform-lesson.yaml"


def use_longform_fixture(content):
    """Every real lesson is now a teaching flow; the older long-form format is still supported (and positional answers
    still protected), so these tests run against one long-form lesson: h.observability as it was before its rewrite."""
    import re

    for f in (content / "en" / "lessons").glob("*.yaml"):
        text = f.read_text(encoding="utf-8")
        m = re.search(r"^- id: h\.observability\n.*?(?=^- id: |\Z)", text, re.M | re.S)
        if m:
            f.write_text(text[: m.start()] + text[m.end():], encoding="utf-8")
    (content / "en" / "lessons" / "zz-longform-fixture.yaml").write_text(LONGFORM.read_text(encoding="utf-8"), encoding="utf-8")


def item(client, kind="lesson", ident="h.observability"):
    response = client.get(f"/api/author/item/{kind}/{ident}", headers=H)
    assert response.status_code == 200, response.text
    return response.json()


def edit(data, source=None):
    return {"kind": data["kind"], "id": data["id"], "yaml": source if source is not None else data["yaml"]}


def changed(data, mutate):
    raw = yaml.safe_load(data["yaml"])
    mutate(raw[0] if data["kind"] != "diagnostic" else raw)
    return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)


def test_off_by_default_and_exact_opt_in(monkeypatch, capsys):
    for value in (None, "0", "true", "yes"):
        if value is None:
            monkeypatch.delenv("ACADEMY_AUTHORING", raising=False)
        else:
            monkeypatch.setenv("ACADEMY_AUTHORING", value)
        with TestClient(main.app, client=("127.0.0.1", 1)) as client:
            assert client.get("/api/meta").json()["authoring"] is False
            assert client.get("/api/author/index", headers=H).status_code == 404
    assert "#token=" not in capsys.readouterr().out


def test_random_token_startup_and_metadata(monkeypatch, capsys):
    monkeypatch.setenv("ACADEMY_AUTHORING", "1")
    monkeypatch.delenv("ACADEMY_AUTHORING_TOKEN", raising=False)
    tokens = []
    for _ in range(2):
        with TestClient(main.app, client=("127.0.0.1", 1)) as client:
            token = main.app.state.author_token
            tokens.append(token)
            meta = client.get("/api/meta")
            assert meta.json()["authoring"] is True
            assert token not in meta.text and "token" not in meta.text
            assert len(token) >= 40
    assert tokens[0] != tokens[1]
    out = capsys.readouterr().out
    assert out.count("/author#token=") == 2
    main.app.state.authoring = False
    main.app.state.author_token = None


@pytest.mark.parametrize("method,url", [
    ("GET", "/index"), ("GET", "/item/lesson/h.observability"), ("POST", "/validate"),
    ("POST", "/preview"), ("GET", "/draft"), ("GET", "/drafts"), ("POST", "/draft"), ("POST", "/publish"),
    ("GET", "/revisions/lesson/h.observability"), ("POST", "/rollback"), ("POST", "/create"),
])
def test_every_endpoint_needs_token_and_loopback(local, method, url):
    assert local.request(method, "/api/author" + url, headers={"X-Academy": "1"}).status_code == 401
    assert local.request(method, "/api/author" + url, headers={**H, "Authorization": "Bearer wrong"}).status_code == 401
    with TestClient(main.app, client=("192.0.2.5", 22)) as remote:
        assert remote.request(method, "/api/author" + url, headers={**H, "X-Forwarded-For": "127.0.0.1"}).status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.2", "::1"])
def test_ipv4_and_ipv6_loopback(local, host):
    with TestClient(main.app, client=(host, 22)) as client:
        assert client.get("/api/author/index", headers=H).status_code == 200


def test_guard_headers_and_no_cache(local):
    assert local.post("/api/author/validate", headers={"Authorization": H["Authorization"]}).status_code == 403
    assert local.get("/api/author/index", headers={**H, "Host": "evil.invalid"}).status_code == 403
    assert local.options("/api/author/index", headers=H).status_code == 403
    result = local.get("/api/author/index", headers=H)
    assert result.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in result.headers
    assert {x["kind"] for x in result.json()} == set(authoring.MODELS)


def test_validation_progress_and_integrity(local):
    data = item(local)
    result = local.post("/api/author/validate", json=edit(data), headers=H).json()
    assert result["ok"], result
    def removed(raw):
        old = raw["sections"][0]["id"]
        raw["sections"][0]["id"] = "renamed-section"
        for question in raw["predict"]:
            for field in ("after", "answered_by"):
                if question.get(field) == old:
                    question[field] = "renamed-section"
    result = local.post("/api/author/validate", json=edit(data, changed(data, removed)), headers=H).json()
    assert not result["ok"] and "section ids" in str(result["errors"])
    source = changed(data, lambda raw: raw["predict"][0].update(prompt="A corrected question prompt?"))
    result = local.post("/api/author/validate", json=edit(data, source), headers=H).json()
    assert result["ok"] and "saved answers" in str(result["warnings"])
    source = changed(data, lambda raw: raw["predict"].reverse())
    result = local.post("/api/author/validate", json=edit(data, source), headers=H).json()
    assert not result["ok"] and "reordered" in str(result["errors"])
    source = changed(data, lambda raw: raw.update(prerequisites=["does.not.exist"]))
    result = local.post("/api/author/validate", json=edit(data, source), headers=H).json()
    assert not result["ok"] and "unknown prerequisite" in str(result["errors"])
    assert not local.post("/api/author/validate", json=edit(data, "- id: h.observability\n  unknown: true"), headers=H).json()["ok"]


@pytest.mark.parametrize("source", ["!!python/object/apply:os.system ['false']", "- &a {id: h.observability, title: A}\n- *a", "- id: h.observability\n  id: other", "- id: other\n"])
def test_unsafe_and_ambiguous_yaml_rejected(local, source):
    assert not local.post("/api/author/validate", json=edit(item(local), source), headers=H).json()["ok"]


def test_preview_same_shape_and_no_write(local):
    data = item(local)
    path = config.CONTENT_ROOT / data["file"]
    before = path.read_bytes()
    original = local.get("/api/lessons/h.observability").json()
    preview = local.post("/api/author/preview", json=edit(data), headers=H)
    assert preview.status_code == 200, preview.text
    assert preview.json() == original
    source = changed(data, lambda raw: raw.update(title="Unsaved title"))
    response = local.post("/api/author/preview", json=edit(data, source), headers=H)
    assert response.json()["title"] == "Unsaved title"
    assert response.json().keys() == original.keys()
    assert path.read_bytes() == before


def test_draft_can_save_invalid_source_privately(local):
    data = item(local)
    path = config.CONTENT_ROOT / data["file"]
    before = path.read_bytes()
    assert local.post("/api/author/draft", json={**edit(data, "unfinished: ["), "base_hash": data["hash"]}, headers=H).status_code == 200
    saved = local.get("/api/author/draft", headers=H).json()
    assert len(saved) == 1 and saved[0]["yaml"] == "unfinished: [" and saved[0]["base_hash"] == data["hash"]
    assert path.read_bytes() == before
    assert_owner_only(config.DATA_DIR / "authoring/drafts/lesson/h.observability.json")


def test_publish_preserves_other_bytes_and_history_round_trip(local):
    data = item(local)
    path = config.CONTENT_ROOT / data["file"]
    # Add comments before/after the selected block; CRLF and Unicode must survive too.
    block = authoring.find("lesson", data["id"])
    original = block.text[:block.start] + "# before — retained\n" + block.source + "# after — retained\n" + block.text[block.end:]
    path.write_bytes(original.replace("\n", "\r\n").encode())
    data = item(local)
    block = authoring.find("lesson", data["id"])
    before = path.read_bytes()
    prefix, suffix = block.text[:block.start].encode(), block.text[block.end:].encode()
    source = data["yaml"]
    raw_title = yaml.safe_load(source)[0]["title"]
    source = source.replace(raw_title, "A revised title", 1)
    result = local.post("/api/author/publish", json={**edit(data, source), "base_hash": data["hash"]}, headers=H)
    assert result.status_code == 200, result.text
    assert path.read_bytes() == prefix + source.encode() + suffix
    history = local.get(f'/api/author/revisions/lesson/{data["id"]}', headers=H).json()
    assert len(history) == 1 and history[0]["yaml"] == data["yaml"]
    revision_file = config.DATA_DIR / "authoring/revisions/lesson" / data["id"] / history[0]["revision"]
    assert_owner_only(revision_file)
    assert local.post("/api/author/rollback", json={"kind": "lesson", "id": data["id"], "revision": history[0]["revision"], "base_hash": data["hash"]}, headers=H).status_code == 409
    restore = local.post("/api/author/rollback", json={"kind": "lesson", "id": data["id"], "revision": history[0]["revision"], "base_hash": result.json()["hash"]}, headers=H)
    assert restore.status_code == 200, restore.text
    assert path.read_bytes() == before
    assert len(local.get(f'/api/author/revisions/lesson/{data["id"]}', headers=H).json()) == 2


def test_publish_refuses_stale_hash_and_invalid_changes(local):
    data = item(local)
    path = config.CONTENT_ROOT / data["file"]
    path.write_bytes(path.read_bytes() + b"\n# external edit\n")
    assert local.post("/api/author/publish", json={**edit(data), "base_hash": data["hash"]}, headers=H).status_code == 409
    data = item(local)
    before = path.read_bytes()
    source = changed(data, lambda raw: raw.update(module="unknown-module"))
    assert local.post("/api/author/publish", json={**edit(data, source), "base_hash": data["hash"]}, headers=H).status_code == 422
    assert path.read_bytes() == before
    assert local.get(f'/api/author/revisions/lesson/{data["id"]}', headers=H).json() == []


def test_post_write_failure_restores_file(local, monkeypatch):
    data = item(local)
    path = config.CONTENT_ROOT / data["file"]
    before = path.read_bytes()
    monkeypatch.setattr(authoring, "whole_problems", lambda: ["injected whole-content error"])
    result = local.post("/api/author/publish", json={**edit(data), "base_hash": data["hash"]}, headers=H)
    assert result.status_code == 422 and path.read_bytes() == before
    assert local.get(f'/api/author/revisions/lesson/{data["id"]}', headers=H).json() == []


@pytest.mark.parametrize("kind", ["module", "track", "route", "diagnostic"])
def test_other_content_kinds_validate_publish_and_restore(local, kind):
    entry = next(x for x in local.get("/api/author/index", headers=H).json() if x["kind"] == kind)
    data = item(local, kind, entry["id"])
    before = (config.CONTENT_ROOT / data["file"]).read_bytes()
    source = changed(data, lambda raw: raw.update(title="Edited title"))
    response = local.post("/api/author/publish", json={**edit(data, source), "base_hash": data["hash"]}, headers=H)
    assert response.status_code == 200, response.text
    response = local.post("/api/author/rollback", json={"kind": kind, "id": data["id"], "revision": response.json()["revision"], "base_hash": response.json()["hash"]}, headers=H)
    assert response.status_code == 200 and (config.CONTENT_ROOT / data["file"]).read_bytes() == before


def test_create_lesson_and_diagnostic(local):
    data = item(local)
    new_source = changed(data, lambda raw: raw.update(id="new.lesson"))
    # Referencing a new lesson is an explicit YAML change, so create can enforce full integrity.
    path = config.content_dir() / "modules.yaml"
    modules = yaml.safe_load(path.read_bytes())
    module = yaml.safe_load(data["yaml"])[0]["module"]
    next(m for m in modules if m["id"] == module)["lessons"].append("new.lesson")
    path.write_text(yaml.safe_dump(modules, sort_keys=False), encoding="utf-8")
    before = (config.CONTENT_ROOT / data["file"]).read_bytes()
    result = local.post("/api/author/create", json={"kind": "lesson", "file": data["file"], "yaml": new_source}, headers=H)
    assert result.status_code == 200, result.text
    assert (config.CONTENT_ROOT / data["file"]).read_bytes().startswith(before)
    assert item(local, ident="new.lesson")["yaml"] == new_source
    assert local.post("/api/author/create", json={"kind": "lesson", "file": data["file"], "yaml": new_source}, headers=H).status_code == 409
    # Add a new available track with an empty diagnostic, without touching the real content.
    tracks = config.content_dir() / "tracks.yaml"
    template = yaml.safe_load(tracks.read_bytes())[0]
    template.update(id="author-test-track", modules=[])
    with tracks.open("a", encoding="utf-8") as stream:
        stream.write(yaml.safe_dump([template], sort_keys=False))
    source = yaml.safe_dump(dict(track="author-test-track", title="New diagnostic", intro="Intro", minutes=5, items=[]))
    result = local.post("/api/author/create", json={"kind": "diagnostic", "file": "en/diagnostics/author-test.yaml", "yaml": source}, headers=H)
    assert result.status_code == 200, result.text
    assert item(local, "diagnostic", "author-test-track")["yaml"] == source


def test_path_traversal_and_symlinks(local, tmp_path):
    data = item(local)
    outside = tmp_path / "outside.yaml"
    outside.write_bytes(b"do not touch")
    for filename in ("../outside.yaml", str(outside), "en/lessons/../../outside.yaml"):
        source = changed(data, lambda raw: raw.update(id="new.lesson"))
        result = local.post("/api/author/create", json={"kind": "lesson", "file": filename, "yaml": source}, headers=H)
        assert result.status_code == 400, result.text
    revision = local.post("/api/author/rollback", json={"kind": "lesson", "id": data["id"], "revision": "../../outside.yaml", "base_hash": data["hash"]}, headers=H)
    assert revision.status_code == 400
    path = config.CONTENT_ROOT / data["file"]
    path.unlink()
    path.symlink_to(outside)
    assert local.get(f'/api/author/item/lesson/{data["id"]}', headers=H).status_code == 400
    assert outside.read_bytes() == b"do not touch"


def test_static_export_disables_authoring(local, tmp_path):
    # A valid temporary copy permits the complete exporter to run under an enabled parent environment.
    out = tmp_path / "export"
    out.mkdir()
    (out / "index.html").write_text('<html><head><title>Test</title></head><body><div id="root"></div></body></html>', encoding="utf-8")
    result = subprocess.run([sys.executable, str(config.ROOT / "scripts/export_static.py"), "--out", str(out)],
                            env={**os.environ, "ACADEMY_CONTENT_DIR": str(config.CONTENT_ROOT)}, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert json.loads((out / "data/meta.json").read_bytes())["authoring"] is False
    assert not (out / "author").exists() and not (out / "data/author").exists()
    assert "test-author-token" not in "".join(p.read_text(encoding="utf-8") for p in out.rglob("*.json"))
    assert "/author#token=" not in result.stdout


def test_rollback_enforces_progress_rules(local):
    data = item(local)
    source = changed(data, lambda raw: raw["sections"].append(dict(id="new-section", title="New section", body="New material.")))
    response = local.post("/api/author/publish", json={**edit(data, source), "base_hash": data["hash"]}, headers=H)
    assert response.status_code == 200, response.text
    published = response.json()
    before = (config.CONTENT_ROOT / data["file"]).read_bytes()
    response = local.post("/api/author/rollback", json={"kind": "lesson", "id": data["id"], "revision": published["revision"]}, headers=H)
    assert response.status_code == 422 and "section ids" in response.text
    assert (config.CONTENT_ROOT / data["file"]).read_bytes() == before


def test_symlinked_runtime_storage_is_refused(local, tmp_path):
    outside = tmp_path / "private-outside"
    outside.mkdir()
    runtime = config.DATA_DIR / "authoring"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.symlink_to(outside, target_is_directory=True)
    data = item(local)
    assert local.post("/api/author/draft", json=edit(data), headers=H).status_code == 400
    assert local.post("/api/author/publish", json={**edit(data), "base_hash": data["hash"]}, headers=H).status_code == 400
    assert list(outside.iterdir()) == []


def test_new_question_append_and_whitespace_prompt_identity(local):
    data = item(local)
    def append(raw):
        raw["predict"][0]["prompt"] = "  " + raw["predict"][0]["prompt"] + "  "
        import copy
        raw["predict"].append({**copy.deepcopy(raw["predict"][-1]), "prompt": "A new appended question?"})
    response = local.post("/api/author/validate", json=edit(data, changed(data, append)), headers=H).json()
    assert response == {"ok": True, "errors": [], "warnings": []}


def test_create_whole_content_failure_removes_new_file(local, monkeypatch):
    # Create a diagnostic for a temporary track with no lessons.
    tracks = config.content_dir() / "tracks.yaml"
    template = yaml.safe_load(tracks.read_bytes())[0]
    template.update(id="create-failure-track", modules=[])
    with tracks.open("a", encoding="utf-8") as stream:
        stream.write(yaml.safe_dump([template], sort_keys=False))
    source = yaml.safe_dump(dict(track="create-failure-track", title="New", intro="Intro", minutes=5, items=[]))
    monkeypatch.setattr(authoring, "whole_problems", lambda: ["injected failure"])
    path = config.content_dir() / "diagnostics/create-failure.yaml"
    result = local.post("/api/author/create", json={"kind": "diagnostic", "file": "en/diagnostics/create-failure.yaml", "yaml": source}, headers=H)
    assert result.status_code == 422 and not path.exists()


def test_tokens_in_urls_and_cookies_are_not_credentials(local):
    assert local.get('/api/author/index?token=test-author-token').status_code == 401
    local.cookies.set('token', 'test-author-token')
    assert local.get('/api/author/index').status_code == 401


def test_non_ip_client_and_missing_peer_are_refused(local):
    with TestClient(main.app, client=('testclient', 1)) as client:
        assert client.get('/api/author/index', headers=H).status_code == 403
    from starlette.requests import Request
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        authoring.require_author(Request({'type': 'http', 'app': main.app, 'headers': [], 'client': None}))
    assert error.value.status_code == 403


def test_eof_without_newline_restores_exact_bytes(local):
    entry = local.get('/api/author/index', headers=H).json()
    entry = next(x for x in entry if x['kind'] == 'diagnostic')
    data = item(local, entry['kind'], entry['id'])
    path = config.CONTENT_ROOT / data['file']
    path.write_bytes(path.read_bytes().rstrip(b'\n'))
    data = item(local, entry['kind'], entry['id'])
    before = path.read_bytes()
    source = changed(data, lambda raw: raw.update(title='No newline round trip')).rstrip('\n')
    published = local.post('/api/author/publish', json={**edit(data, source), 'base_hash': data['hash']}, headers=H)
    assert published.status_code == 200, published.text
    response = local.post('/api/author/rollback', json={'kind': data['kind'], 'id': data['id'], 'revision': published.json()['revision']}, headers=H)
    assert response.status_code == 200 and path.read_bytes() == before


@pytest.mark.parametrize('method,path', [('GET', '/unknown'), ('GET', ''), ('GET', '/validate'), ('DELETE', '/index'), ('HEAD', '/item/lesson/h.observability')])
def test_author_namespace_guard_also_covers_unknown_paths_and_methods(local, method, path):
    response = local.request(method, '/api/author' + path, headers={'X-Academy':'1'})
    assert response.status_code == 401
    with TestClient(main.app, client=('192.0.2.1', 1)) as client:
        assert client.request(method, '/api/author' + path, headers=H).status_code == 403
    if method == 'GET' and path in ('', '/unknown', '/validate'):
        assert local.get('/api/author' + path, headers=H).status_code == 404


def test_flow_lessons_get_teaching_standard_warnings(local):
    data = item(local, ident="lx.first-steps")
    source = data["yaml"].replace("The files are the same; you reach them", "The files are the same; you just reach them")
    assert source != data["yaml"]
    result = local.post("/api/author/validate", json=edit(data, source), headers=H).json()
    assert result["ok"], result
    assert any(w.startswith("Teaching standard:") and "'just'" in w for w in result["warnings"])
    # a new demonstration whose command was never recorded is reported, not refused
    source = data["yaml"].replace("      run: ls -F\n", "      run: ls -F --color=never\n").replace("    - cmd: ls -F\n", "    - cmd: ls -F --color=never\n")
    result = local.post("/api/author/validate", json=edit(data, source), headers=H).json()
    assert result["ok"], result
    assert any("is not recorded yet" in w for w in result["warnings"])


def _listing(kind):
    return [(b.kind, b.id, b.title, b.path, b.text, b.start, b.end) for b in authoring.blocks(kind)]


def test_blocks_parse_a_file_again_only_when_its_text_changes(local, monkeypatch):
    """authoring.blocks() keeps each file's parse keyed by its exact text: the same listing without parsing unchanged
    files again, and a change of one byte is parsed again (no stale ids, titles or offsets)."""
    parsed = []
    real = authoring._parse_entries
    monkeypatch.setattr(authoring, "_parse_entries", lambda kind, text: parsed.append(kind) or real(kind, text))
    authoring._PARSED.clear()
    files = sorted((config.content_dir() / "lessons").glob("*.yaml"))
    first = _listing("lesson")
    assert len(parsed) == len(files)
    assert _listing("lesson") == first and len(parsed) == len(files)  # unchanged: from the memo, identical
    block = authoring.find("lesson", "h.observability")
    edited = block.text.replace(block.source, block.source.replace("- id: h.observability", "- id: h.observability-renamed", 1), 1)
    assert edited != block.text
    block.path.write_bytes(edited.encode("utf-8"))
    parsed.clear()
    after = _listing("lesson")
    assert parsed == ["lesson"]  # only the changed file
    assert "h.observability-renamed" in [b[1] for b in after] and "h.observability" not in [b[1] for b in after]
    authoring._PARSED.clear()
    assert _listing("lesson") == after  # the same as a parse without the memo


def test_a_memoised_file_still_passes_the_path_checks_and_names_its_file(local, tmp_path):
    """The memo holds parses only: a file whose text was parsed before is still refused when it becomes a symbolic
    link, and a parse error names the file that has it now."""
    block = authoring.find("lesson", "h.observability")  # its text is now memoised
    outside = tmp_path / "outside.yaml"
    outside.write_bytes(block.text.encode("utf-8"))  # the same text, elsewhere
    block.path.unlink()
    block.path.symlink_to(outside)
    with pytest.raises(authoring.HTTPException) as refused:
        authoring.blocks("lesson")
    assert refused.value.status_code == 400
    block.path.unlink()
    lessons = config.content_dir() / "lessons"
    for name in ("a-broken.yaml", "b-broken.yaml"):
        (lessons / name).write_text("- id: x\n  id: y\n", encoding="utf-8")  # a duplicate key
        with pytest.raises(authoring.HTTPException) as broken:
            authoring.blocks("lesson")
        assert broken.value.status_code == 422 and broken.value.detail.startswith(f"{name}: duplicate YAML keys"), broken.value.detail
        (lessons / name).unlink()
