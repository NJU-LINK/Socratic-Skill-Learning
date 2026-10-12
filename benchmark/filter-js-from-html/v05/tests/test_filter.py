from __future__ import annotations

import base64
import html
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.parse
from pathlib import Path

import pytest
from bs4 import BeautifulSoup


FILTER = Path("/app/filter.py")


def _b64_html(payload: str) -> str:
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def _entity_encode(text: str) -> str:
    return "".join(html.escape(ch) if ch in "<>&\"'" else ch for ch in text)


def _percent_encode(text: str) -> str:
    return urllib.parse.quote(text, safe="")


def clean_html_samples() -> list[str]:
    return [
        """<!DOCTYPE html>
<html>
<head><title>Status Board</title></head>
<body>
  <main>
    <h1>Quarterly update</h1>
    <p>Revenue is up 14% and hiring remains open.</p>
    <table>
      <tr><th>Region</th><th>Result</th></tr>
      <tr><td>North</td><td>Strong</td></tr>
    </table>
  </main>
</body>
</html>""",
        """<section class="card card--notice" data-team="ops">
  <h2>Maintenance window</h2>
  <p>Please save your work before 22:00 UTC.</p>
  <a href="/status">View status page</a>
</section>""",
        """<!DOCTYPE html>
<html>
<body>
  <form action="/signup" method="post">
    <label>Email <input type="email" name="email" required></label>
    <button type="submit">Join</button>
  </form>
</body>
</html>""",
    ]


def dangerous_html_samples() -> list[str]:
    script = "<script>alert('alpha')</script>"
    entity_script = _entity_encode("<script>alert('entity')</script>")
    pct_script = _percent_encode("javascript:alert('pct')")
    embedded = "<script>confirm(7)</script>"
    embedded_b64 = _b64_html(embedded)
    nested_svg = "<svg><g onload=alert('svg')></g></svg>"
    nested_svg_entity = _entity_encode(nested_svg)
    doc = "<html><body><script>alert('doc')</script><p>ok</p></body></html>"

    return [
        script,
        "<ScRiPt >alert('case')</ScRiPt>",
        "<img src=x onerror='alert(1)'>",
        "<body onpageshow='alert(2)'><p>hello</p></body>",
        f'<a href="javascript:alert(3)">open</a>',
        f'<a href="{pct_script}">open</a>',
        '<iframe src="data:text/html;base64,' + embedded_b64 + '"></iframe>',
        '<object data="data:text/html;base64,' + embedded_b64 + '"></object>',
        '<iframe src="/page.html" title="embedded page"></iframe>',
        '<object data="/doc.html" type="text/html"></object>',
        '<embed src="/widget.svg" type="image/svg+xml">',
        '<meta http-equiv="refresh" content="0;url=javascript:alert(4)">',
        '<meta http-equiv="REFRESH" content="0; URL = javascript:alert(4)">',
        '<meta http-equiv="refresh" content=" 0 ; url = JaVaScRiPt:alert(4) ">',
        '<form action="javascript:alert(5)"><input type="submit"></form>',
        '<button formaction="javascript:alert(6)">Ship</button>',
        nested_svg,
        '<math><maction actiontype="statusline" xlink:href="javascript:alert(8)"></maction></math>',
        '<div style="background-image:url(javascript:alert(9))">x</div>',
        "<<script>alert('broken');//<</script>",
        entity_script,
        nested_svg_entity,
        '<template><img src=x onerror="alert(10)"></template><div>later</div>',
        '<iframe srcdoc="<script>alert(11)</script>"></iframe>',
        '<svg><foreignObject><iframe src="javascript:alert(12)"></iframe></foreignObject></svg>',
        '<input type="image" formaction="javascript:alert(13)" src="/safe.png">',
        '<details open ontoggle="alert(14)"><summary>More</summary></details>',
        doc,
    ]


def wrapped_corpus() -> list[dict[str, str]]:
    wrappers = [
        "<!DOCTYPE html>\n<html><head><title>{name}</title></head><body>{payload}</body></html>",
        "<html><body><div class=outer><p>prefix</p>{payload}<footer>suffix</footer></div></body></html>",
        "<table><tr><td>{payload}</td><td>notes</td></tr></table>",
        "<template id=t>{payload}</template><section>preview</section>",
        "<svg><foreignObject>{payload}</foreignObject></svg>",
    ]

    corpus = []
    for index, payload in enumerate(dangerous_html_samples()):
        wrapper = wrappers[index % len(wrappers)]
        corpus.append(
            {
                "name": f"dangerous-{index:02d}",
                "payload": payload,
                "document": wrapper.format(name=f"Sample {index}", payload=payload),
            }
        )

    for index, payload in enumerate(clean_html_samples()):
        corpus.append(
            {
                "name": f"clean-{index:02d}",
                "payload": payload,
                "document": payload,
            }
        )

    return corpus


def run_filter(html_text: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        sample = Path(tmpdir) / "sample.html"
        sample.write_text(html_text, encoding="utf-8")
        subprocess.run([sys.executable, str(FILTER), str(sample)], check=True)
        return sample.read_text(encoding="utf-8")


def has_unsafe_dom(html_text: str) -> bool:
    soup = BeautifulSoup(html_text, "html.parser")

    if soup.find("script") is not None:
        return True

    if soup.find(["iframe", "object", "embed"]) is not None:
        return True

    for tag in soup.find_all(True):
        for attr_name, attr_value in tag.attrs.items():
            name = attr_name.lower()
            value = " ".join(attr_value) if isinstance(attr_value, list) else str(attr_value)
            normalized = html.unescape(value)
            for _ in range(3):
                decoded = urllib.parse.unquote(normalized)
                if decoded == normalized:
                    break
                normalized = decoded
            normalized = re.sub(r"[\x00-\x20]+", "", normalized.lower())
            if name.startswith("on"):
                return True
            if name == "srcdoc":
                return True
            if name in {"href", "src", "data", "action", "formaction", "xlink:href"} and (
                normalized.startswith("javascript:")
                or normalized.startswith("vbscript:")
                or normalized.startswith("data:text/html")
                or normalized.startswith("data:image/svg+xml")
            ):
                return True
            if name == "style" and (
                "expression(" in normalized
                or "url(javascript:" in normalized
                or "url(data:text/html" in normalized
            ):
                return True

        if tag.name and tag.name.lower() == "meta":
            equiv = str(tag.attrs.get("http-equiv", "")).lower()
            content = html.unescape(str(tag.attrs.get("content", "")))
            for _ in range(3):
                decoded = urllib.parse.unquote(content)
                if decoded == content:
                    break
                content = decoded
            if equiv == "refresh" and re.search(r"url\s*=\s*(javascript:|vbscript:)", content, flags=re.IGNORECASE):
                return True

    return False


def text_snapshot(html_text: str) -> str:
    return " ".join(BeautifulSoup(html_text, "html.parser").stripped_strings)


@pytest.fixture(scope="module")
def filter_exists():
    assert FILTER.exists(), "solution did not create /app/filter.py"
    return FILTER


def test_preserves_clean_samples(filter_exists):
    clean_samples = clean_html_samples()
    assert clean_samples, "expected clean samples"

    for original in clean_samples:
        sanitized = run_filter(original)
        before = BeautifulSoup(original, "html.parser")
        after = BeautifulSoup(sanitized, "html.parser")

        assert text_snapshot(sanitized) == text_snapshot(original)
        assert len(after.find_all("form")) == len(before.find_all("form"))
        assert len(after.find_all("table")) == len(before.find_all("table"))
        assert len(after.find_all("a")) == len(before.find_all("a"))

        if before.find("section") is not None:
            section = after.find("section")
            assert section is not None
            assert section.get("class") == before.find("section").get("class")
            assert section.get("data-team") == "ops"

        if before.find("form") is not None:
            form = after.find("form")
            assert form is not None
            assert form.get("action") == "/signup"
            assert form.get("method") == "post"


def test_sanitizes_wrapped_dangerous_corpus(filter_exists):
    wrapped = wrapped_corpus()
    dangerous = [entry for entry in wrapped if entry["name"].startswith("dangerous-")]
    assert dangerous, "expected dangerous samples"

    for entry in dangerous:
        sanitized = run_filter(entry["document"])
        assert not has_unsafe_dom(sanitized), entry["name"]

        original_text = text_snapshot(entry["document"])
        sanitized_text = text_snapshot(sanitized)
        for marker in ("prefix", "suffix", "notes", "preview", "later", "ok"):
            if marker in original_text:
                assert marker in sanitized_text, entry["name"]


def test_browser_does_not_execute_remaining_content():
    selenium = pytest.importorskip("selenium")
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By

    html_text = textwrap.dedent(
        """\
        <!doctype html>
        <html>
          <body data-fired="no">
            <p id="safe">still here</p>
            <script>document.body.dataset.fired = 'script';</script>
            <img src="missing.png" onerror="document.body.dataset.fired='onerror'">
            <a id="go" href="javascript:document.body.dataset.fired='href'">go</a>
          </body>
        </html>
        """
    )

    sanitized = run_filter(html_text)
    assert "still here" in sanitized
    assert not has_unsafe_dom(sanitized)

    with tempfile.TemporaryDirectory() as tmpdir:
        page = Path(tmpdir) / "page.html"
        page.write_text(sanitized, encoding="utf-8")

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        if Path("/usr/bin/chromium").exists():
            options.binary_location = "/usr/bin/chromium"

        service = Service("/usr/bin/chromedriver") if Path("/usr/bin/chromedriver").exists() else Service()
        driver = webdriver.Chrome(service=service, options=options)
        try:
            driver.get(page.as_uri())
            driver.find_element(By.ID, "go").click()
            time.sleep(0.2)
            fired = driver.execute_script("return document.body.dataset.fired")
            text = driver.find_element(By.TAG_NAME, "body").text
        finally:
            driver.quit()

    assert fired == "no"
    assert "still here" in text
