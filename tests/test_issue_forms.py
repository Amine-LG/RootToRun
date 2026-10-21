"""GitHub hides an issue form whose YAML does not match its schema, without any error: three of the four forms were
missing from the new-issue page because an unquoted comma inside a `{...}` mapping turned the end of a description
into an extra attribute. These checks follow GitHub's documented issue-form syntax."""
import re

import yaml

from academy import config

FORMS = config.ROOT / ".github" / "ISSUE_TEMPLATE"
TOP = {"name", "description", "title", "labels", "assignees", "projects", "type", "body"}
# each element type's attributes and the type GitHub requires for each (GitHub's issue-form syntax documentation)
STR, LIST = (str,), (list,)
ATTRIBUTES = {
    "markdown": {"value": STR},
    "input": {"label": STR, "description": STR, "placeholder": STR, "value": STR},
    "textarea": {"label": STR, "description": STR, "placeholder": STR, "value": STR, "render": STR},
    "dropdown": {"label": STR, "description": STR, "multiple": (bool,), "options": LIST, "default": (int,)},
    "checkboxes": {"label": STR, "description": STR, "options": LIST},
}


def forms():
    found = sorted(p for p in FORMS.glob("*.y*ml") if p.name != "config.yml")
    assert len(found) == 4, [p.name for p in found]
    return found


def test_every_issue_form_matches_githubs_schema():
    for path in forms():
        form = yaml.safe_load(path.read_text(encoding="utf-8"))
        where = path.name
        assert set(form) <= TOP, (where, set(form) - TOP)
        assert form.get("name") and form.get("description") and form.get("body"), where
        assert isinstance(form["name"], str) and isinstance(form["description"], str) and isinstance(form["body"], list), where
        for key in ("title", "type"):
            assert isinstance(form.get(key, ""), str), (where, key)
        for key in ("labels", "assignees", "projects"):  # a list of strings, or one comma-separated string
            v = form.get(key, [])
            assert isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, str) for x in v)), (where, key, v)
        ids = set()
        for element in form["body"]:
            kind = element.get("type")
            assert kind in ATTRIBUTES, (where, kind)
            assert set(element) <= {"type", "id", "attributes", "validations"}, (where, element)
            attributes = element.get("attributes") or {}
            assert set(attributes) <= set(ATTRIBUTES[kind]), (where, element.get("id"), set(attributes) - set(ATTRIBUTES[kind]))
            for name, value in attributes.items():
                want = ATTRIBUTES[kind][name]
                # bool is an int in Python: a `default: true` must not pass for an option index
                assert isinstance(value, want) and not (want == (int,) and isinstance(value, bool)), (where, element.get("id"), name, value)
            if kind != "markdown":
                assert attributes.get("label"), (where, element)
                assert re.fullmatch(r"[A-Za-z0-9_-]+", element.get("id", "")), (where, element.get("id"))
                assert element["id"] not in ids, (where, element["id"])
                ids.add(element["id"])
            else:
                assert "validations" not in element and "id" not in element, where
            validations = element.get("validations") or {}
            assert isinstance(validations, dict) and set(validations) <= {"required"}, (where, element.get("id"))
            assert all(isinstance(v, bool) for v in validations.values()), (where, element.get("id"), validations)  # `required: true`, not a string or a list
            if kind == "markdown":
                assert attributes.get("value"), where
            if kind == "dropdown":
                options = attributes.get("options")
                assert options and all(isinstance(o, str) and o for o in options) and len(options) == len(set(options)), (where, element.get("id"))
                assert 0 <= attributes.get("default", 0) < len(options), (where, element.get("id"))
            if kind == "checkboxes":
                options = attributes.get("options")
                assert options and all(isinstance(o, dict) and isinstance(o.get("label"), str) and o["label"] and set(o) <= {"label", "required"}
                                       and isinstance(o.get("required", False), bool) for o in options), (where, element.get("id"))
                assert len({o["label"] for o in options}) == len(options), (where, element.get("id"))


def _linked_forms():
    """The forms the site's report links open and the fields they fill (FORMS in frontend/src/lib/contribute.ts)."""
    source = (config.ROOT / "frontend" / "src" / "lib" / "contribute.ts").read_text(encoding="utf-8")
    table = source[source.index("export const FORMS = {"):]
    table = table[: table.index("} as const")]
    found = {k: (f, re.findall(r"'([\w-]+)'", fields)) for k, f, fields in re.findall(r"(\w+): \{ file: '([\w.-]+)', fields: \[([^\]]*)\] \}", table)}
    assert set(found) == {"content", "command", "website"}, found
    return found


def test_every_report_link_fills_only_fields_that_exist_in_its_form():
    """A query parameter that names no field of the form is silently dropped by GitHub: every field a report link fills
    must be an input or textarea of the form it opens (dropdowns are left for the reporter)."""
    for key, (name, fields) in _linked_forms().items():
        path = FORMS / name
        assert path.exists(), (key, name)
        form = yaml.safe_load(path.read_text(encoding="utf-8"))
        kinds = {e.get("id"): e["type"] for e in form["body"] if e.get("id")}
        assert fields, key
        for field in fields:
            assert kinds.get(field) in ("input", "textarea"), (name, field, kinds.get(field))
        assert "page-url" in fields and "site-version" in fields, key


def test_content_and_website_problems_are_different_forms():
    forms = _linked_forms()
    content = yaml.safe_load((FORMS / forms["content"][0]).read_text(encoding="utf-8"))
    website = yaml.safe_load((FORMS / forms["website"][0]).read_text(encoding="utf-8"))
    assert forms["content"][0] != forms["website"][0]
    assert "content" in content["labels"] and "ui" in website["labels"]
    assert "browser" not in forms["website"][1]  # the reporter says which browser; the link never reads it


def test_blank_issues_stay_off():
    assert yaml.safe_load((FORMS / "config.yml").read_text(encoding="utf-8"))["blank_issues_enabled"] is False
