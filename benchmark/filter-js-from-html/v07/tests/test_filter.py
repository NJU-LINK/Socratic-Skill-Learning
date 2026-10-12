from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path


FIXTURES_DIR = Path(os.environ.get("FIXTURES_DIR", "/app/fixtures"))
CASES_PATH = FIXTURES_DIR / "navigation_cases.json"


class TagCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[dict[str, object]] = []
        self._stack: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = {
            "tag": tag,
            "attrs": {key: value or "" for key, value in attrs},
            "text": "",
            "parent": self._stack[-1] if self._stack else None,
        }
        self.tags.append(node)
        self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = {
            "tag": tag,
            "attrs": {key: value or "" for key, value in attrs},
            "text": "",
            "parent": self._stack[-1] if self._stack else None,
        }
        self.tags.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index]["tag"] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self._stack:
            self._stack[-1]["text"] += data


def parse_html(html: str) -> TagCollector:
    parser = TagCollector()
    parser.feed(html)
    return parser


def find_tag(parser: TagCollector, tag: str, **attrs: str) -> dict[str, object] | None:
    for node in parser.tags:
        if node["tag"] != tag:
            continue
        node_attrs = node["attrs"]
        if all(node_attrs.get(key) == value for key, value in attrs.items()):
            return node
    return None


def find_tags(parser: TagCollector, tag: str) -> list[dict[str, object]]:
    return [node for node in parser.tags if node["tag"] == tag]


def class_list(node: dict[str, object]) -> list[str]:
    value = node["attrs"].get("class", "")
    return [item for item in value.split() if item]


def tag_text(node: dict[str, object]) -> str:
    return " ".join(node["text"].split())


def run_filter(source_name: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        working = Path(tmpdir) / source_name
        shutil.copy(FIXTURES_DIR / source_name, working)
        subprocess.run([sys.executable, "/app/filter.py", str(working)], check=True)
        return working.read_text(encoding="utf-8")


def run_filter_on_html(html_text: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        working = Path(tmpdir) / "inline.html"
        working.write_text(html_text, encoding="utf-8")
        subprocess.run([sys.executable, "/app/filter.py", str(working)], check=True)
        return working.read_text(encoding="utf-8")


def load_cases() -> list[dict[str, str]]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def test_all_fixture_cases_are_covered() -> None:
    cases = load_cases()
    assert {case["html_file"] for case in cases} == {
        "checkout-page-dangerous-form-action.html",
        "account-settings-button-formaction.html",
        "admin-console-nav-links.html",
        "search-page-meta-refresh.html",
        "contact-page-data-link.html",
    }


def test_sanitizes_dangerous_form_and_button_targets_only() -> None:
    checkout_html = run_filter("checkout-page-dangerous-form-action.html")
    checkout = parse_html(checkout_html)
    form = find_tag(checkout, "form", **{"data-flow": "checkout-v2"})
    assert form is not None
    assert form["attrs"].get("action") == "#"
    assert class_list(form) == ["stacked", "checkout-form"]
    assert form["attrs"].get("data-flow") == "checkout-v2"
    assert find_tag(checkout, "input", id="full-name")["attrs"].get("value") == "Morgan Lee"

    return_link = next(
        node for node in find_tags(checkout, "a")
        if class_list(node) == ["button", "secondary"]
    )
    assert return_link["attrs"].get("href") == "/cart"

    account_html = run_filter("account-settings-button-formaction.html")
    account = parse_html(account_html)
    buttons = find_tags(account, "button")
    assert [tag_text(button) for button in buttons] == ["Save changes", "Export profile"]
    assert class_list(buttons[0]) == ["btn", "btn-primary"]
    assert buttons[1]["attrs"].get("formaction") == "#"
    assert buttons[1]["attrs"].get("formmethod") == "post"
    settings_form = next(node for node in find_tags(account, "form") if "settings-form" in class_list(node))
    assert settings_form["attrs"].get("action") == "/account/settings"


def test_sanitizes_unsafe_links_but_keeps_safe_navigation() -> None:
    admin_html = run_filter("admin-console-nav-links.html")
    admin = parse_html(admin_html)
    nav_links = [
        node for node in find_tags(admin, "a")
        if node["parent"] is not None
        and node["parent"]["tag"] == "nav"
        and "topnav" in class_list(node["parent"])
    ]
    assert [tag_text(link) for link in nav_links] == [
        "Overview",
        "Audit Log",
        "Team Users",
        "Billing",
        "Security Help",
    ]
    assert [link["attrs"].get("href") for link in nav_links] == [
        "/admin/overview",
        "#",
        "#",
        "/admin/billing?tab=invoices",
        "/help/security",
    ]

    contact_html = run_filter("contact-page-data-link.html")
    contact = parse_html(contact_html)
    docs_link = next(node for node in find_tags(contact, "a") if "docs-link" in class_list(node))
    assert docs_link is not None
    assert docs_link["attrs"].get("href") == "#"
    assert tag_text(docs_link) == "Troubleshooting guide"
    contact_form = next(node for node in find_tags(contact, "form") if "contact-form" in class_list(node))
    assert contact_form["attrs"].get("action") == "/support/request"
    assert find_tag(contact, "input", id="subject")["attrs"].get("value") == "Billing question"


def test_removes_dangerous_meta_refresh_and_preserves_page_content() -> None:
    search_html = run_filter("search-page-meta-refresh.html")
    search = parse_html(search_html)
    metas = find_tags(search, "meta")
    assert all(meta["attrs"].get("http-equiv", "").lower() != "refresh" for meta in metas)
    title = find_tag(search, "title")
    assert title is not None
    assert tag_text(title) == "Search Redirect"
    form = next(node for node in find_tags(search, "form") if "search-form" in class_list(node))
    assert form is not None
    assert form["attrs"].get("action") == "/search"
    assert form["attrs"].get("method") == "get"
    fallback = next(node for node in find_tags(search, "a") if "fallback-link" in class_list(node))
    assert fallback["attrs"].get("href") == "/search?q=portable+monitor"
    assert find_tag(search, "input", id="search-query")["attrs"].get("value") == "portable monitor"

    assert not re.search(r"<meta[^>]*http-equiv=[\"']refresh[\"']", search_html, flags=re.IGNORECASE)


def test_sanitizes_active_container_tags_and_nested_obfuscation() -> None:
    sample = """<!DOCTYPE html>
    <html lang=\"en\">
    <head><title>Embedded content</title></head>
    <body class=\"dashboard shell\">
      <main class=\"panel\">
        <iframe class=\"report-frame\" src=\"javas%2563ript:alert(1)\" loading=\"lazy\"></iframe>
        <embed class=\"plugin-view\" src=\"data:text/html,%3Cscript%3Ealert(2)%3C/script%3E\" type=\"text/html\">
        <object class=\"legacy-widget\" data=\"JaVaScRiPt:alert(3)\" width=\"320\" height=\"180\"></object>
        <a class=\"safe-link\" href=\"/reports/current\">Current report</a>
      </main>
    </body>
    </html>"""

    filtered_html = run_filter_on_html(sample)
    parsed = parse_html(filtered_html)

    iframe = next(node for node in find_tags(parsed, "iframe") if "report-frame" in class_list(node))
    assert iframe["attrs"].get("src") == ""
    assert iframe["attrs"].get("loading") == "lazy"

    embed = next(node for node in find_tags(parsed, "embed") if "plugin-view" in class_list(node))
    assert embed["attrs"].get("src") == ""
    assert embed["attrs"].get("type") == "text/html"

    obj = next(node for node in find_tags(parsed, "object") if "legacy-widget" in class_list(node))
    assert obj["attrs"].get("data") == ""
    assert obj["attrs"].get("width") == "320"
    assert obj["attrs"].get("height") == "180"

    safe_link = next(node for node in find_tags(parsed, "a") if "safe-link" in class_list(node))
    assert safe_link["attrs"].get("href") == "/reports/current"
    assert tag_text(find_tag(parsed, "title")) == "Embedded content"


def test_decodes_entities_and_double_encoding_before_classifying_urls() -> None:
    sample = """<!DOCTYPE html>
    <html>
    <body>
      <a class=\"encoded-link\" href=\"&#106;ava&#115;cript:alert(9)\">Encoded</a>
      <form class=\"profile-form\" action=\"javas%2563ript:alert(7)\" method=\"post\">
        <input id=\"nickname\" value=\"tay\" class=\"field compact\">
      </form>
      <iframe class=\"video\" src=\"data:text/html,%253Cscript%253Ealert(4)%253C/script%253E\"></iframe>
      <a class=\"ok-link\" href=\"/help/profile\">Help</a>
    </body>
    </html>"""

    filtered_html = run_filter_on_html(sample)
    parsed = parse_html(filtered_html)

    encoded_link = next(node for node in find_tags(parsed, "a") if "encoded-link" in class_list(node))
    assert encoded_link["attrs"].get("href") == "#"

    profile_form = next(node for node in find_tags(parsed, "form") if "profile-form" in class_list(node))
    assert profile_form["attrs"].get("action") == "#"
    assert profile_form["attrs"].get("method") == "post"
    assert find_tag(parsed, "input", id="nickname")["attrs"].get("value") == "tay"

    iframe = next(node for node in find_tags(parsed, "iframe") if "video" in class_list(node))
    assert iframe["attrs"].get("src") == ""

    ok_link = next(node for node in find_tags(parsed, "a") if "ok-link" in class_list(node))
    assert ok_link["attrs"].get("href") == "/help/profile"


def test_preserves_benign_embedded_urls_while_neutralizing_unsafe_ones() -> None:
    sample = """<!DOCTYPE html>
    <html>
    <body class=\"media-page\">
      <iframe class=\"safe-frame\" src=\"/widgets/weather?view=compact\" loading=\"lazy\"></iframe>
      <iframe class=\"bad-frame\" src=\"javascript:alert(1)\" loading=\"eager\"></iframe>
      <embed class=\"safe-embed\" src=\"/assets/manual.pdf#page=2\" type=\"application/pdf\">
      <embed class=\"bad-embed\" src=\"data:text/html,%3Cscript%3Ealert(2)%3C/script%3E\" type=\"text/html\">
      <object class=\"safe-object\" data=\"/media/chart.svg\" width=\"640\" height=\"360\"></object>
      <object class=\"bad-object\" data=\"jAvAsCrIpT:alert(3)\" width=\"320\" height=\"180\"></object>
    </body>
    </html>"""

    filtered_html = run_filter_on_html(sample)
    parsed = parse_html(filtered_html)

    safe_frame = next(node for node in find_tags(parsed, "iframe") if "safe-frame" in class_list(node))
    assert safe_frame["attrs"].get("src") == "/widgets/weather?view=compact"
    assert safe_frame["attrs"].get("loading") == "lazy"

    bad_frame = next(node for node in find_tags(parsed, "iframe") if "bad-frame" in class_list(node))
    assert bad_frame["attrs"].get("src") == ""
    assert bad_frame["attrs"].get("loading") == "eager"

    safe_embed = next(node for node in find_tags(parsed, "embed") if "safe-embed" in class_list(node))
    assert safe_embed["attrs"].get("src") == "/assets/manual.pdf#page=2"
    assert safe_embed["attrs"].get("type") == "application/pdf"

    bad_embed = next(node for node in find_tags(parsed, "embed") if "bad-embed" in class_list(node))
    assert bad_embed["attrs"].get("src") == ""
    assert bad_embed["attrs"].get("type") == "text/html"

    safe_object = next(node for node in find_tags(parsed, "object") if "safe-object" in class_list(node))
    assert safe_object["attrs"].get("data") == "/media/chart.svg"
    assert safe_object["attrs"].get("width") == "640"
    assert safe_object["attrs"].get("height") == "360"

    bad_object = next(node for node in find_tags(parsed, "object") if "bad-object" in class_list(node))
    assert bad_object["attrs"].get("data") == ""
    assert bad_object["attrs"].get("width") == "320"
    assert bad_object["attrs"].get("height") == "180"
