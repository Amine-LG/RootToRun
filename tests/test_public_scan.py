"""scripts/public_scan.py: vendor course or exam codes and certification phrases are refused, ordinary text is not.

The prohibited strings below are assembled from pieces, so that this file itself passes the scan it tests.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from public_scan import CERT, CODE, scan, shown  # noqa: E402


def j(*parts: str) -> str:
    return "".join(parts)


def findings(tmp_path: Path, text: str, name: str = "page.md") -> list[str]:
    (tmp_path / name).write_text(text, encoding="utf-8")
    return scan(tmp_path, [name])


CODES = [
    j("EX", "280"), j("ex", "280"), j("Ex", "-280"), j("EX", " 280"), j("ex", " 280"), j("e", "x-380"),
    j("DO", "280"), j("do", "180"), j("DO", "-188"), j("DO", " 380"), j("Do", "480"),
    j("RH", "124"), j("rh", "134"), j("RH", " 294"), j("rh", "-294"),
    j("CL", "110"), j("AD", "141"),
    j("Revise for ", "EX", "294"), j("(", "do", "280)"), j("slug: ", "do", "280-review"),
]
PHRASES = [
    j("RH", "CSA"), j("rh", "ce"), j("RH", "CAs"), j("an ", "RH", "CE-level task"),
    j("Red Hat ", "Certified Engineer"), j("red hat ", "certified specialist"),
    j("the ", "exam ", "objectives"), j("Exam ", "Objective 3"),
    j("a ", "certification ", "exam"), j("Certification ", "Exams"),
    j("Red Hat OpenShift ", "Administration I"), j("Red Hat OpenShift ", "Administration II"),
    j("Red Hat OpenShift ", "Administration III"), j("Red Hat OpenShift ", "Developer I"),
]


@pytest.mark.parametrize("text", CODES)
def test_codes_are_refused_in_any_case_and_spacing(tmp_path, text):
    out = findings(tmp_path, f"line one\n{text} here\n")
    assert len(out) == 1 and f"page.md:2: {CODE}: " in out[0]


@pytest.mark.parametrize("text", PHRASES)
def test_certification_titles_and_exam_phrases_are_refused(tmp_path, text):
    out = findings(tmp_path, text)
    assert len(out) == 1 and CERT in out[0]


ORDINARY = [
    "Renew the router's TLS certificate before it expires; certificates signed by the service CA.",
    "certified-operators   Certified Operators   grpc   Red Hat     197d",
    "MS-DOS, DOS 6.22, a DoS attack and DOSBox",
    "do 100 requests, then do 200 more; Do 300 pods fit?",
    "RHEL 9, rhel9, RHCOS nodes, RHACS policies, RHSSO, a RHEL-9 host",
    "sha256:ad123ef4567890abcdef1234567890abcdef1234567890abcdef1234567890ab",
    "image@sha256:0123ad1234cl123ex1239876543210fedcba9876543210fedcba9876543210",
    "pod/web-6d8f9c7b5d-x2kq7 and replicaset web-6d8f9c7b5d; deadbeef cafe0123",
    "exit 127, index 100, the exam room, learning objectives, ex. 3, rh.example.com",
    "lowercase ad123 and cl110 inside generated hex strings",
    "admin1, admin2, osa.progress, X-NET-01, X-SELF-03",
    "The course is not a certification course and contains no exam content.",
]


@pytest.mark.parametrize("text", ORDINARY)
def test_ordinary_text_passes(tmp_path, text):
    assert findings(tmp_path, text) == []


def test_red_hat_certified_is_refused_even_before_a_product_word(tmp_path):
    # refused wherever it appears as one phrase; recorded catalog tables separate "Red Hat" from "Certified Operators"
    # by several spaces, and test_real_content_has_no_course_reference checks the real recordings
    assert len(findings(tmp_path, j("Red Hat ", "Certified Operators catalogue"))) == 1


def test_finding_never_shows_the_whole_value(tmp_path):
    code = j("EX", "280")
    out = findings(tmp_path, code)
    assert out == [f"page.md:1: {CODE}: EX…"] and code not in out[0]
    assert shown("abcdefghijklmnop") == "abcdef" and shown("ab") == "a" and shown("x") == "x"


def test_private_terms_still_apply(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_TREE_PRIVATE", "Alpha Example, beta-host")
    out = findings(tmp_path, "contact alpha example on BETA-HOST")
    assert out == ["page.md:1: a private term", "page.md:1: a private term"]


def test_real_content_has_no_course_reference():
    """The course content, recordings and app sources (hex digests, pod names, base64 data) raise no code or phrase."""
    tracked = subprocess.run(["git", "ls-files", "content", "frontend/src", "backend", "README.md", "CONTRIBUTING.md"],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout.split()
    files = [f for f in tracked if not f.startswith("content/drafts/")]
    assert len(files) > 300
    hits = [f for f in scan(ROOT, files) if CODE in f or CERT in f]
    assert hits == []


def test_development_tools_are_refused_but_the_public_credit_is_not(tmp_path):
    assert len(findings(tmp_path, j("notes from a Cl", "aude session and a Co", "dex review"))) == 2
    assert len(findings(tmp_path, j("cl", "aude, CO", "DEX, see CL", "AUDE.md"))) == 3  # any case, file names too
    credit = "with AI-assisted development using models from Anthropic and OpenAI"
    assert findings(tmp_path, credit) == []
