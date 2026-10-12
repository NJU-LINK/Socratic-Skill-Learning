from __future__ import annotations

import hashlib
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
from bs4 import BeautifulSoup


FILTER = Path("/app/filter.py")
DATA = Path("/app/data")
EXPECTED_NORMALIZED_SHA256 = {
    "editorial-fragile-input.html": "97db5ae6699a62164ce95ef182391fdcb58594de5c94465713413099c0252487",
    "editorial-briefing-input.html": "3b52ee722bd74cc7f5d428865c05a01748bcecbb7578ad7ae7ab921e5b66b58a",
}


def normalize(html: str) -> str:
    return html.replace("\r\n", "\n").strip()


def run_filter_path(path: Path) -> str:
    assert FILTER.is_file(), "/app/filter.py was not created"
    subprocess.run(["python3", str(FILTER), str(path)], check=True)
    return path.read_text(encoding="utf-8")


def filter_fixture(name: str, tmp_path: Path) -> str:
    target = tmp_path / name
    shutil.copy(DATA / name, target)
    return run_filter_path(target)


def filter_html(tmp_path: Path, name: str, html: str) -> str:
    target = tmp_path / name
    target.write_text(textwrap.dedent(html).lstrip(), encoding="utf-8")
    return run_filter_path(target)


@pytest.mark.parametrize("name", sorted(EXPECTED_NORMALIZED_SHA256))
def test_editorial_inputs_match_private_expected_digest(name: str, tmp_path: Path):
    filtered = normalize(filter_fixture(name, tmp_path))
    assert hashlib.sha256(filtered.encode()).hexdigest() == EXPECTED_NORMALIZED_SHA256[name]


def test_clean_editorial_reference_is_unchanged(tmp_path: Path):
    original = (DATA / "editorial-clean-reference.html").read_text(encoding="utf-8")
    assert normalize(filter_fixture("editorial-clean-reference.html", tmp_path)) == normalize(original)


def test_fragile_page_preserves_navigation_caption_and_preformatted_text(tmp_path: Path):
    soup = BeautifulSoup(filter_fixture("editorial-fragile-input.html", tmp_path), "html.parser")
    assert not soup.find("script")
    assert all(
        not any(attribute.lower().startswith("on") for attribute in tag.attrs)
        for tag in soup.find_all(True)
    )
    assert [link.get_text(strip=True) for link in soup.select("nav a")] == [
        "Overview",
        "Survey notes",
        "Archive",
    ]
    assert "Boarding canopy draft" in soup.find("figcaption").get_text()
    assert soup.find("pre").get_text() == (
        "Boarding windows\n06:15  southbound\n06:42  express\n07:05  shuttle"
    )


def test_briefing_page_preserves_form_and_table_but_removes_active_targets(tmp_path: Path):
    soup = BeautifulSoup(filter_fixture("editorial-briefing-input.html", tmp_path), "html.parser")
    assert not soup.find("iframe")
    form = soup.find("form")
    assert form.get("method") == "post"
    assert form.get("action") is None
    assert "Check status" in form.get_text(" ", strip=True)
    assert soup.find("a", href="#appendix").get_text(strip=True) == "this anchor"
    assert soup.find("table") is not None


def test_synthetic_vectors_require_general_sanitization(tmp_path: Path):
    filtered = filter_html(
        tmp_path,
        "fresh-editorial.html",
        """
        <!DOCTYPE html>
        <html><head>
          <meta http-equiv="refresh" content="0; url='javascript:alert(1)'">
          <meta http-equiv="refresh" content="5; url=/safe/digest.html">
        </head><body>
          <article>
            <h1>Daily bulletin</h1>
            <p onclick="alert(2)">Reading room status stays public.</p>
            <a href="javascript%3Aalert(3)">Unsafe action</a>
            <a href="/bulletins/today#details">Safe action</a>
            <svg><a xlink:href="data:text/html,%3Cscript%3Ealert(4)%3C/script%3E"><text>Vector note</text></a></svg>
            <figure><figcaption>Caption <script>alert(5)</script> keeps the rest.</figcaption></figure>
          </article>
        </body></html>
        """,
    )
    soup = BeautifulSoup(filtered, "html.parser")
    assert soup.find("h1").get_text(strip=True) == "Daily bulletin"
    assert not soup.find("script")
    assert soup.find("p").get("onclick") is None
    links = soup.find_all("a")
    assert links[0].get("href") is None
    assert links[1].get("href") == "/bulletins/today#details"
    assert soup.find("text").get_text(strip=True) == "Vector note"
    refresh = soup.find_all("meta", attrs={"http-equiv": "refresh"})
    assert refresh[0].get("content") is None
    assert refresh[1].get("content") == "5; url=/safe/digest.html"
