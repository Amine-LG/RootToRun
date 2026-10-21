"""Lesson screenshots (academy/media.py): a show step's `image` names a PNG in content/media/<lesson id>/; content
checks refuse a missing or oversized file, the API adds its address and size, the practice server serves it, and the
static export copies it and puts it in the pre-rendered page. The PNG here is a generated test fixture."""
import importlib.util
import shutil
import struct
import zlib

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from academy import config, curriculum, labs, main, media

LID = "lx.first-steps"
STEP = {"kind": "show", "id": "console-shot", "title": "Where you are", "body": "Look at the top bar.",
        "image": {"src": "where.png", "alt": "The top bar of the page, with the project name at the left",
                  "captured": "test fixture (generated), not a real screenshot"},
        "caption": "The top bar", "notice": "The project name is at the left."}


def png(w: int, h: int) -> bytes:
    raw = b"".join(b"\x00" + b"\x7f\x7f\x7f" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


@pytest.fixture
def content(tmp_path, monkeypatch):
    root = tmp_path / "content"
    shutil.copytree(config.CONTENT_ROOT / "en", root / "en")
    shutil.copytree(config.CONTENT_ROOT / "recordings", root / "recordings")
    shutil.copytree(config.CONTENT_ROOT / "media", root / "media")  # the course's own screenshots
    monkeypatch.setattr(config, "CONTENT_ROOT", root)
    monkeypatch.setattr(config, "RECORDINGS_DIR", root / "recordings")
    for f in (root / "en" / "lessons").glob("*.yaml"):
        items = yaml.safe_load(f.read_text(encoding="utf-8"))
        for item in items:
            if item["id"] == LID:
                item["flow"].insert(1, STEP)
                f.write_text(yaml.safe_dump(items, sort_keys=False, allow_unicode=True), encoding="utf-8")
    curriculum._cache.clear()
    labs._cache.clear()
    yield root
    curriculum._cache.clear()
    labs._cache.clear()


def problems():
    return curriculum.integrity(set(labs.load("en")), "en")


def test_a_screenshot_needs_its_file(content):
    assert [p for p in problems() if "image" in p] == [f"lesson {LID}: image where.png: no file content/media/{LID}/where.png"]
    (content / "media" / LID).mkdir(parents=True)
    (content / "media" / LID / "where.png").write_bytes(b"not a png")
    assert any("not a whole PNG file" in p for p in problems())
    (content / "media" / LID / "where.png").write_bytes(png(40, 30))
    assert problems() == []


def test_an_oversized_screenshot_is_refused(content, monkeypatch):
    (content / "media" / LID).mkdir(parents=True)
    (content / "media" / LID / "where.png").write_bytes(png(40, 30))
    monkeypatch.setattr(media, "MAX_BYTES", 10)
    assert any("more than 10" in p for p in problems())


def test_a_show_step_has_one_source_and_a_screenshot_says_what_it_shows():
    base = {k: v for k, v in STEP.items() if k != "image"}
    with pytest.raises(ValidationError, match="exactly one of"):
        curriculum.Show(**base, image=STEP["image"], code="x: 1")
    with pytest.raises(ValidationError):
        curriculum.Show(**base, image={**STEP["image"], "alt": "screenshot"})  # alt text that says nothing
    with pytest.raises(ValidationError):
        curriculum.Show(**base, image={k: v for k, v in STEP["image"].items() if k != "captured"})  # provenance
    with pytest.raises(ValidationError):
        curriculum.Show(**base, image={**STEP["image"], "src": "../where.png"})
    assert curriculum.Show(**base, image=STEP["image"]).image.src == "where.png"


def test_the_api_gives_the_address_and_size_and_serves_the_file(content):
    (content / "media" / LID).mkdir(parents=True)
    (content / "media" / LID / "where.png").write_bytes(png(40, 30))
    c = TestClient(main.app)
    step = next(s for s in c.get(f"/api/lessons/{LID}").json()["flow"] if s["id"] == "console-shot")
    assert step["image"] == {**STEP["image"], "url": f"/media/{LID}/where.png", "width": 40, "height": 30}
    r = c.get(f"/media/{LID}/where.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    for bad in (f"/media/{LID}/missing.png", f"/media/{LID}/where.svg", f"/media/{LID}/Where.png"):
        assert c.get(bad).status_code == 404, bad
    for outside in ("/media/..%2Fen/where.png", f"/media/{LID}/..%2F..%2Fen%2Flessons"):  # never a file outside media/
        r = c.get(outside)
        assert r.headers.get("content-type") != "image/png" and b"lessons:" not in r.content, outside


def test_the_static_export_copies_it_and_prerenders_it(content, tmp_path):
    (content / "media" / LID).mkdir(parents=True)
    (content / "media" / LID / "where.png").write_bytes(png(40, 30))
    spec = importlib.util.spec_from_file_location("export_static", config.ROOT / "scripts" / "export_static.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    # the script imports the backend as `backend.academy`: point that copy at this content too
    ex.config.CONTENT_ROOT, ex.config.RECORDINGS_DIR = content, content / "recordings"
    ex.curriculum._cache.clear()
    ex.labs._cache.clear()
    out = tmp_path / "site"
    out.mkdir()
    (out / "index.html").write_text('<!doctype html><html><head><title>x</title></head><body><div id="root"></div><script src="/a.js"></script></body></html>', encoding="utf-8")
    assert ex.export(out, None) == 0
    assert (out / "media" / LID / "where.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    from academy import urls
    page = (out / urls.table()["lessons"][LID].lstrip("/") / "index.html").read_text(encoding="utf-8")
    assert f'<img src="/media/{LID}/where.png" alt="{STEP["image"]["alt"]}" width="40" height="30"' in page
    assert "The top bar · test fixture (generated), not a real screenshot" in page


def test_a_symbolic_link_is_never_served_or_exported(content, tmp_path):
    (content / "media" / LID).mkdir(parents=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(png(40, 30))
    (content / "media" / LID / "where.png").symlink_to(outside)  # a "screenshot" that is a file elsewhere
    assert media.path(LID, "where.png") is None
    assert any("no file" in p for p in problems())
    assert TestClient(main.app).get(f"/media/{LID}/where.png").headers.get("content-type") != "image/png"
    (content / "media" / "other").mkdir()
    (content / "media" / "other" / "where.png").write_bytes(png(40, 30))
    (content / "media" / LID / "where.png").unlink()
    (content / "media" / LID).rmdir()
    (content / "media" / LID).symlink_to(content / "media" / "other")  # the lesson's directory itself is a link
    assert media.path(LID, "where.png") is None


@pytest.mark.parametrize("data", [png(40, 30)[:-12], png(40, 30)[:30], png(0, 30), png(5000, 30)], ids=["no-end", "header-only", "zero-wide", "too-wide"])
def test_a_broken_or_absurd_png_is_refused(content, data):
    (content / "media" / LID).mkdir(parents=True)
    (content / "media" / LID / "where.png").write_bytes(data)
    assert any("not a whole PNG" in p for p in problems())


def test_alt_text_and_provenance_cannot_be_blank():
    base = {k: v for k, v in STEP.items() if k != "image"}
    for field in ("alt", "captured"):
        with pytest.raises(ValidationError):
            curriculum.Show(**base, image={**STEP["image"], field: " " * 40})


def test_a_missing_file_leaves_the_lesson_readable(content):
    """The file disappears after the content was checked: the lesson still loads, and the image has no size."""
    c = TestClient(main.app)
    r = c.get(f"/api/lessons/{LID}")
    assert r.status_code == 200
    step = next(s for s in r.json()["flow"] if s["id"] == "console-shot")
    assert (step["image"]["width"], step["image"]["height"]) == (0, 0)


def test_a_screenshot_is_revalidated_by_the_browser(content):
    (content / "media" / LID).mkdir(parents=True)
    (content / "media" / LID / "where.png").write_bytes(png(40, 30))
    assert TestClient(main.app).get(f"/media/{LID}/where.png").headers["cache-control"] == "no-cache"  # replaced files show at once


def test_exporting_again_drops_a_screenshot_no_longer_used(content, tmp_path):
    (content / "media" / LID).mkdir(parents=True)
    (content / "media" / LID / "where.png").write_bytes(png(40, 30))
    spec = importlib.util.spec_from_file_location("export_static", config.ROOT / "scripts" / "export_static.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    ex.config.CONTENT_ROOT, ex.config.RECORDINGS_DIR = content, content / "recordings"
    out = tmp_path / "site"
    out.mkdir()
    (out / "index.html").write_text('<!doctype html><html><head><title>x</title></head><body><div id="root"></div></body></html>', encoding="utf-8")
    ex.curriculum._cache.clear()
    assert ex.export(out, None) == 0 and (out / "media" / LID / "where.png").exists()
    (out / "media" / "old-lesson").mkdir()
    (out / "media" / "old-lesson" / "gone.png").write_bytes(png(4, 4))  # from an earlier export
    ex.curriculum._cache.clear()
    assert ex.export(out, None) == 0
    assert not (out / "media" / "old-lesson").exists() and (out / "media" / LID / "where.png").exists()
