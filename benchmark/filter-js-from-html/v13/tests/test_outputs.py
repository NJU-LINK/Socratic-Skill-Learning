import html
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup


sys.path.insert(0, "/app")


URL_ATTRS = {
    "href",
    "src",
    "action",
    "formaction",
    "xlink:href",
    "poster",
    "background",
    "data",
}


def decode_repeatedly(value: str) -> str:
    current = value
    for _ in range(6):
        decoded = html.unescape(unquote(current))
        if decoded == current:
            break
        current = decoded
    return current


def normalize_for_scheme_check(value: str) -> str:
    import re

    decoded = decode_repeatedly(value)
    return re.sub(r"[\x00-\x20\x7f]+", "", decoded).lower()


def is_dangerous_url(value: str) -> bool:
    normalized = normalize_for_scheme_check(value)
    if normalized.startswith(("javascript:", "vbscript:")):
        return True
    if normalized.startswith("data:"):
        media_type = normalized[5:].split(",", 1)[0].split(";", 1)[0]
        return media_type in {
            "text/html",
            "application/xhtml+xml",
            "image/svg+xml",
            "text/xml",
        }
    return False


def run_filter(html_text: str) -> str:
    assert Path("/app/filter.py").exists(), "filter.py does not exist"

    with tempfile.NamedTemporaryFile("w+", suffix=".html", delete=False) as handle:
        path = Path(handle.name)
        path.write_text(html_text, encoding="utf-8")

    try:
        result = subprocess.run(
            ["python", "/app/filter.py", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return path.read_text(encoding="utf-8")
    finally:
        path.unlink(missing_ok=True)


def test_filter_neutralizes_fragmented_payloads():
    original = """<!DOCTYPE html>
<html>
  <head>
    <title>Publishable fragment</title>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="0; URL = jav&#x61;script:alert(9)">
  </head>
  <body>
    <article id="story" class="rich prose" data-keep="yes">
      <h1>Launch plan</h1>
      <p>
        <a class="cta" title="read more" data-track="hero"
           href="jav&#x61;%73cript&#x3a;alert(1)">Read more</a>
      </p>
      <form action="ja&#118;ascript:alert(2)" method="post" data-safe="1">
        <input type="text" name="email" value="reader@example.com">
        <button formaction="jav&#x61;script:alert(3)" class="primary">Send</button>
      </form>
      <img src="/images/cover.png" alt="Cover image" onerror="alert(4)">
      <div style="background-image:url(javascript:alert(5)); color: red">Styled block</div>
      <template>
        <a data-template="x" href="java&#x73;cript:alert(6)">Template link</a>
      </template>
      <iframe src="data:text/html,%3Cscript%3Ealert(7)%3C/script%3E"></iframe>
    </article>
  </body>
</html>"""

    filtered = run_filter(original)
    soup = BeautifulSoup(filtered, "html.parser")

    assert soup.find("article", {"id": "story"}) is not None
    assert soup.find("h1").get_text(strip=True) == "Launch plan"
    assert "Read more" in soup.get_text(" ", strip=True)
    assert soup.find("meta", attrs={"http-equiv": True}) is None
    assert soup.find("iframe") is None

    for tag in soup.find_all(True):
        for attr_name, attr_value in tag.attrs.items():
            joined = " ".join(attr_value) if isinstance(attr_value, list) else str(attr_value)
            assert not attr_name.lower().startswith("on"), (tag.name, attr_name, joined)
            assert attr_name.lower() != "srcdoc"
            if attr_name.lower() in URL_ATTRS:
                assert not is_dangerous_url(joined), (tag.name, attr_name, joined)
            if attr_name.lower() == "style":
                normalized = normalize_for_scheme_check(joined)
                assert "expression(" not in normalized
                assert "url(javascript:" not in normalized

    link = soup.find("a", string="Read more")
    assert link is not None
    assert link.get("class") == ["cta"]
    assert link.get("title") == "read more"
    assert link.get("data-track") == "hero"
    assert link.get("href") == "#"

    form = soup.find("form")
    assert form is not None
    assert form.get("method") == "post"
    assert form.get("data-safe") == "1"
    assert form.get("action") is None
    assert soup.find("button").get("formaction") is None

    img = soup.find("img")
    assert img is not None
    assert img.get("src") == "/images/cover.png"
    assert img.get("alt") == "Cover image"
    assert img.get("onerror") is None

    template_link = soup.find("a", string="Template link")
    assert template_link is not None
    assert template_link.find_parent("template") is not None
    assert template_link.get("data-template") == "x"
    assert template_link.get("href") == "#"


def test_filter_removes_direct_script_but_preserves_safe_base():
    html_text = """<!DOCTYPE html>
<html>
  <head>
    <base href="https://cdn.example.com/assets/" target="_self">
    <script>alert(1)</script>
  </head>
  <body>
    <a href="guide.html" class="doc-link">Guide</a>
  </body>
</html>"""

    filtered = run_filter(html_text)
    soup = BeautifulSoup(filtered, "html.parser")

    assert soup.find("script") is None

    base = soup.find("base")
    assert base is not None
    assert base.get("href") == "https://cdn.example.com/assets/"
    assert base.get("target") == "_self"

    link = soup.find("a", string="Guide")
    assert link is not None
    assert link.get("href") == "guide.html"
    assert link.get("class") == ["doc-link"]


def test_filter_neutralizes_dangerous_base_href_without_dropping_tag():
    html_text = """<!DOCTYPE html>
<html>
  <head>
    <base href="jav&#x61;script:alert(1)" target="_blank">
  </head>
  <body>
    <p>Preserve me</p>
  </body>
</html>"""

    filtered = run_filter(html_text)
    soup = BeautifulSoup(filtered, "html.parser")

    base = soup.find("base")
    assert base is not None
    assert base.get("href") is None
    assert base.get("target") == "_blank"
    assert soup.find("p").get_text(strip=True) == "Preserve me"


def test_filter_preserves_clean_html_structure():
    clean = """<!DOCTYPE html>
<html>
  <head>
    <title>Quarterly report</title>
    <base href="https://reports.example.com/2026/">
  </head>
  <body>
    <main class="report" data-version="2026.06">
      <nav><a href="/home">Home</a> <a href="/reports">Reports</a></nav>
      <section>
        <h1>Results</h1>
        <p>Revenue grew by <strong>12%</strong> this quarter.</p>
        <table>
          <tr><th>Region</th><th>Growth</th></tr>
          <tr><td>North</td><td>12%</td></tr>
        </table>
      </section>
      <form action="/subscribe" method="post">
        <input type="email" name="email" value="reader@example.com">
        <button type="submit">Subscribe</button>
      </form>
      <img src="/static/chart.png" alt="Growth chart">
    </main>
  </body>
</html>"""

    filtered = run_filter(clean)
    assert str(BeautifulSoup(filtered, "html.parser")) == str(BeautifulSoup(clean, "html.parser"))


def test_filter_modifies_target_file_in_place():
    html_text = '<a href="javascript:alert(1)" data-id="42">Go</a>'

    with tempfile.NamedTemporaryFile("w+", suffix=".html", delete=False) as handle:
        path = Path(handle.name)
        path.write_text(html_text, encoding="utf-8")

    try:
        before = path.read_text(encoding="utf-8")
        result = subprocess.run(
            ["python", "/app/filter.py", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        after = path.read_text(encoding="utf-8")
    finally:
        path.unlink(missing_ok=True)

    assert result.returncode == 0, result.stderr
    assert before != after
    soup = BeautifulSoup(after, "html.parser")
    link = soup.find("a")
    assert link is not None
    assert link.get("data-id") == "42"
    assert link.get("href") == "#"
