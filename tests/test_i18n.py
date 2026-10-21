"""Localisation: a language overlays translated items on English; everything else falls back to English."""
import shutil

import pytest
import yaml

from academy import config, curriculum, labs


@pytest.fixture
def xx(tmp_path, monkeypatch):
    root = tmp_path / "content"
    shutil.copytree(config.CONTENT_ROOT / "en", root / "en")
    shutil.copytree(config.CONTENT_ROOT / "recordings", root / "recordings")
    (root / "xx" / "lessons").mkdir(parents=True)
    monkeypatch.setattr(config, "CONTENT_ROOT", root)
    monkeypatch.setattr(config, "RECORDINGS_DIR", root / "recordings")
    monkeypatch.setattr(config, "LANGS", ("en", "xx"))
    curriculum._cache.clear()
    labs._cache.clear()
    yield root
    curriculum._cache.clear()
    labs._cache.clear()


def english(lid):
    for f in (config.CONTENT_ROOT / "en" / "lessons").glob("*.yaml"):
        for item in yaml.safe_load(f.read_text(encoding="utf-8")):
            if item["id"] == lid:
                return item
    raise KeyError(lid)


def translate(item, stamp=None):
    t = {**item, "title": "XX " + item["title"]}
    if "sections" in item:
        t["sections"] = [{**s, "body": "xx " + s["body"]} for s in item["sections"]]
    if "predict" in item:
        t["predict"] = [{**q, "prompt": "xx " + q["prompt"]} for q in item["predict"]]
    if "flow" in item:
        t["flow"] = [{**st, **({"body": "xx " + st["body"]} if st.get("body") else {}), **({"prompt": "xx " + st["prompt"]} if st.get("prompt") else {})} for st in item["flow"]]
    if stamp:
        t["source"] = stamp
    return t


def test_translated_lesson_overlays_english_and_keeps_question_ids(xx):
    en = curriculum.load("en")
    lid = "lx.shell-basics"
    stamp = curriculum.source_hash(en["lessons"][lid])
    (xx / "xx/lessons/t.yaml").write_text(yaml.safe_dump([translate(english(lid), stamp)], allow_unicode=True), encoding="utf-8")
    d = curriculum.load("xx")
    assert d["errors"] == en["errors"]
    assert d["lessons"][lid].title.startswith("XX ")
    assert [q.id for q in d["lessons"][lid].predict] == [q.id for q in en["lessons"][lid].predict]  # answers carry over
    assert d["translation"]["lessons"] == {lid: "translated"}
    other = "lx.files-text"
    assert d["lessons"][other] is en["lessons"][other]  # untranslated: English
    assert curriculum.integrity(set(labs.load("xx")), "xx") == curriculum.integrity(set(labs.load("en")), "en")


def test_a_translation_of_an_older_english_version_is_stale(xx):
    lid = "lx.shell-basics"
    (xx / "xx/lessons/t.yaml").write_text(yaml.safe_dump([translate(english(lid), "000000000000")], allow_unicode=True), encoding="utf-8")
    assert curriculum.load("xx")["translation"]["lessons"][lid] == "stale"


def test_a_translation_may_not_change_structure(xx):
    lid = "lx.users-scheduling"  # a lesson's depth sections keep their ids
    t = translate(english(lid))
    t["sections"][0]["id"] = "renamed"
    # a flow lesson: a translation may reword every step but not change a question's answer or a command
    t3 = translate(english("lx.first-steps"))
    ask = next(st for st in t3["flow"] if st["kind"] == "ask")
    ask["answer"] = (ask["answer"] + 1) % len(ask["choices"])
    (xx / "xx/lessons/t.yaml").write_text(yaml.safe_dump([t, t3], allow_unicode=True), encoding="utf-8")
    d = curriculum.load("xx")
    assert any("section ids" in e for e in d["errors"]) and any("choices and answer" in e for e in d["errors"])
    assert any("lx.first-steps" in e and "flow step" in e for e in d["errors"])
    assert d["lessons"][lid] is curriculum.load("en")["lessons"][lid]


def test_a_translated_lab_may_change_only_prose(xx):
    (xx / "xx" / "labs").mkdir()
    src = next((config.CONTENT_ROOT / "en" / "labs").glob("*.yaml"))
    lab = yaml.safe_load(src.read_text(encoding="utf-8"))
    ok = {**lab, "title": "XX " + lab["title"]}
    (xx / "xx/labs/ok.yaml").write_text(yaml.safe_dump(ok, allow_unicode=True), encoding="utf-8")
    assert labs.load("xx")[lab["id"]].title.startswith("XX ")
    bad = {**lab, "namespace": lab["namespace"] + "-x"}
    (xx / "xx/labs/ok.yaml").write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    labs._cache.clear()
    assert labs.load("xx")[lab["id"]].title == lab["title"]
    assert any("only prose" in e for e in labs.errors("xx"))
