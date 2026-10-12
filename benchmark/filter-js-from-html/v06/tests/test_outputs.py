import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


FILTER = Path("/app/filter.py")
SAMPLES = Path("/app/samples")


def run_filter(path: Path) -> str:
    assert FILTER.is_file(), "/app/filter.py was not created"
    result = subprocess.run(
        ["python3", str(FILTER), str(path)],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    return path.read_text(encoding="utf-8")


def filter_html(html: str, filename="input.html") -> str:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / filename
        path.write_text(html, encoding="utf-8")
        return run_filter(path)


def browser_has_alert(path: Path) -> bool:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(path.resolve().as_uri())
        try:
            WebDriverWait(driver, 2).until(EC.alert_is_present())
        except TimeoutException:
            return False
        driver.switch_to.alert.accept()
        return True
    finally:
        driver.quit()


@pytest.mark.parametrize(
    ("sample", "dangerous_fragments"),
    [
        (
            "facility-map.html",
            [
                "onload = \"alert('map-ready')\"",
                '<script>\n          alert("inline-svg-script");\n        </script>',
            ],
        ),
        (
            "overview-dashboard.html",
            ["xlink:href=\"javas&#99;ript:alert('overview-link')\""],
        ),
        (
            "release-pipeline.html",
            [
                "XLINK:href='javas&#x63;ript:alert(\"pipeline-click\")'",
                "to=\"javascript:alert('pipeline-animate')\"",
            ],
        ),
    ],
)
def test_large_svg_samples_remove_only_declared_unsafe_fragments(sample, dangerous_fragments):
    original = (SAMPLES / sample).read_text(encoding="utf-8")
    expected = original
    for fragment in dangerous_fragments:
        expected = expected.replace(fragment, "")

    assert filter_html(original, sample) == expected


def test_clean_svg_article_is_byte_preserved():
    html = """<!DOCTYPE html>
<html lang="en">
  <body>
    <article>
      <svg viewBox="0 0 100 60" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
        <defs><linearGradient id="g"><stop offset="0%" stop-color="#fff" /></linearGradient></defs>
        <a xlink:href="/docs/diagram"><text x="5" y="20">Safe link</text></a>
        <rect x="5" y="25" width="40" height="20" fill="url(#g)" />
      </svg>
    </article>
  </body>
</html>"""
    assert filter_html(html, "clean.html") == html


@pytest.mark.parametrize(
    ("html", "removed", "preserved"),
    [
        (
            """<svg onload='alert(1)'><a xlink:href=' jAva&#x73;cript:alert(2) '><text>Label</text></a><animate attributeName='xlink:href' to='java&#115;cript:alert(3)' /></svg>""",
            ["onload=", "xlink:href=", "to="],
            ["<text>Label</text>"],
        ),
        (
            """<head><meta http-equiv="refresh" content="0;url=jav%61script:alert(1)"><meta http-equiv="refresh" content="5;url=/status"></head><body><p>Keep body</p></body>""",
            ['content="0;url=jav%61script:alert(1)"'],
            ['content="5;url=/status"', "<p>Keep body</p>"],
        ),
        (
            """<body><iframe srcdoc="<script>alert(1)</script>"><p>Fallback</p></iframe><p>Trailing</p></body>""",
            ["<iframe"],
            ["<p>Trailing</p>"],
        ),
        (
            """<body><object data="javascript:alert(1)">Blocked</object><embed src='data:text/html,<script>alert(2)</script>' /><p>Caption</p></body>""",
            ["<object", "<embed"],
            ["<p>Caption</p>"],
        ),
        (
            """<form action="javascript:alert(1)"><button>Launch</button></form><form action="/safe"><button formaction='java&#115;cript:alert(2)'>Override</button></form>""",
            ['action="javascript:alert(1)"', "formaction="],
            ["<button>Launch</button>", 'action="/safe"'],
        ),
        (
            """<math><mi xlink:href="javascript:alert(1)">x</mi></math><div style="width:expression(alert(2))">Expression</div>""",
            ["xlink:href=", "style="],
            [">x</mi>", ">Expression</div>"],
        ),
        (
            """<a href="jav%61script:alert(1)">Encoded</a><img src="d%61ta:text/html,<script>alert(2)</script>" alt="Preview"><p>Text</p>""",
            ["href=", "src="],
            ["Encoded</a>", 'alt="Preview"', "<p>Text</p>"],
        ),
    ],
)
def test_executable_vectors_are_removed_with_safe_neighbors_preserved(html, removed, preserved):
    filtered = filter_html(html, "vector.html")
    for fragment in removed:
        assert fragment not in filtered
    for fragment in preserved:
        assert fragment in filtered


def test_sample_outputs_have_no_script_event_or_javascript_scheme():
    for source in sorted(SAMPLES.glob("*.html")):
        filtered = filter_html(source.read_text(encoding="utf-8"), source.name)
        soup = BeautifulSoup(filtered, "html.parser")
        assert not soup.find_all("script")
        for tag in soup.find_all(True):
            for name, value in tag.attrs.items():
                assert not name.lower().startswith("on")
                values = value if isinstance(value, list) else [value]
                assert all("javascript:" not in str(item).lower().replace(" ", "") for item in values)


def test_filtered_samples_do_not_execute_in_browser():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for source in sorted(SAMPLES.glob("*.html")):
            target = root / source.name
            shutil.copyfile(source, target)
            run_filter(target)
            assert not browser_has_alert(target), f"alert executed for {source.name}"
