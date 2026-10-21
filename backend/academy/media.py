"""Images shown in lessons: real screenshots, never mock-ups. A lesson's images live in content/media/<lesson id>/ and
are served at /media/<lesson id>/<file> (the practice server, the dev proxy and the static export alike). Only PNG, the
format screenshots are saved in; the size is read from the file, so a page reserves the space before the image loads."""
import re
import struct
from pathlib import Path

from . import config

MAX_BYTES = 1_500_000  # a readable screenshot of a browser window stays well under this as PNG
MAX_SIDE = 4096  # pixels: a screenshot of a large screen; a bigger image is not a screenshot
LESSON = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*\.png$")
_PNG = b"\x89PNG\r\n\x1a\n"


def root() -> Path:
    return config.CONTENT_ROOT / "media"


def path(lesson: str, name: str) -> Path | None:
    """The file for /media/<lesson>/<name>, or None for a name that is not a lesson image. A symbolic link (of the
    file or of the lesson's directory) never counts: only a file really in content/media/<lesson>/ is served."""
    if not LESSON.match(lesson) or not NAME.match(name):
        return None
    p = root() / lesson / name
    try:
        real = p.resolve()
    except OSError:
        return None
    return p if real == root().resolve() / lesson / name else None


def url(lesson: str, name: str) -> str:
    return f"/media/{lesson}/{name}"


def png_size(p: Path) -> tuple[int, int] | None:
    """Width and height from the PNG header (IHDR), or None when the file is not a whole PNG (it must also end with
    the IEND chunk) of 1 to MAX_SIDE pixels a side, or cannot be read."""
    try:
        with p.open("rb") as f:
            head = f.read(24)
            f.seek(-12, 2)
            tail = f.read(12)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != _PNG or head[12:16] != b"IHDR" or tail[4:8] != b"IEND":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return (w, h) if 0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE else None


def images(lesson) -> list:
    """The lesson's screenshots, in flow order."""
    return [st.image for st in (lesson.flow or []) if getattr(st, "image", None)]


def problems(lessons) -> list[str]:
    out = []
    for l in lessons:
        for img in images(l):
            p = path(l.id, img.src)
            where = f"lesson {l.id}: image {img.src}"
            if p is None or not p.is_file():
                out.append(f"{where}: no file content/media/{l.id}/{img.src}")
            elif p.stat().st_size > MAX_BYTES:
                out.append(f"{where}: {p.stat().st_size} bytes, more than {MAX_BYTES}: crop it or reduce its colours")
            elif not png_size(p):
                out.append(f"{where}: not a whole PNG file of 1 to {MAX_SIDE} pixels a side")
    return out


def info(lesson: str, name: str) -> dict:
    """What a page needs to show the image: its address and its size (0 x 0 when the file is missing or unreadable:
    the page then says the image is unavailable, the lesson still loads)."""
    p = path(lesson, name)
    w, h = (png_size(p) if p else None) or (0, 0)
    return {"url": url(lesson, name), "width": w, "height": h}
