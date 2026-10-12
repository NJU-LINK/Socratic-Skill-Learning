import subprocess
import sys
from pathlib import Path

from bs4 import BeautifulSoup


FILTER = Path("/app/filter.py")


def run_filter(tmp_path, html_text):
    html_file = tmp_path / "sample.html"
    html_file.write_text(html_text, encoding="utf-8")
    subprocess.run([sys.executable, str(FILTER), str(html_file)], check=True)
    return html_file.read_text(encoding="utf-8")


def parse_fragment(text):
    return BeautifulSoup(text, "html.parser")


def test_svg_scripts_and_dangerous_links_are_removed_but_safe_content_remains(tmp_path):
    output = run_filter(
        tmp_path,
        """
        <!doctype html>
        <html>
          <body>
            <article>
              <svg viewBox="0 0 10 10">
                <script>alert(1)</script>
                <a xlink:href="java&#x73;cript:alert(1)"><text>bad</text></a>
                <use href="javascript:alert(1)#icon"></use>
                <circle cx="5" cy="5" r="4"></circle>
                <text>diagram label</text>
              </svg>
              <math>
                <mi>x</mi><mo>+</mo><mi>y</mi>
              </math>
              <a href="/docs/reference">safe link</a>
            </article>
          </body>
        </html>
        """,
    )
    soup = parse_fragment(output)

    assert not soup.find("script")
    assert soup.find("circle") is not None
    assert "diagram label" in [node.get_text(strip=True) for node in soup.find_all("text")]
    assert soup.find("math") is not None
    assert soup.find("a", href="/docs/reference") is not None

    svg_link = soup.find("svg").find("a")
    assert svg_link is not None
    assert not svg_link.has_attr("xlink:href")

    use_tag = soup.find("use")
    assert use_tag is not None
    assert not use_tag.has_attr("href")


def test_foreign_object_events_and_refresh_navigation_are_neutralized(tmp_path):
    output = run_filter(
        tmp_path,
        """
        <html>
          <head>
            <meta http-equiv="refresh" content="0; URL = jav&#x61;script:alert(1)">
          </head>
          <body>
            <svg>
              <foreignObject><body onload="alert(1)">boom</body></foreignObject>
              <set attributeName="xlink:href" to="javascript:alert(1)"></set>
              <animate attributeName="fill" values="red;blue"></animate>
              <rect width="10" height="10" onclick="evil()"></rect>
            </svg>
          </body>
        </html>
        """,
    )
    soup = parse_fragment(output)

    assert soup.find("meta") is None
    assert soup.find("foreignobject") is None
    assert soup.find("set") is None

    animate = soup.find("animate")
    assert animate is not None
    assert animate.get("attributename") == "fill"

    rect = soup.find("rect")
    assert rect is not None
    assert not rect.has_attr("onclick")


def test_form_actions_and_formactions_are_sanitized_without_breaking_safe_forms(tmp_path):
    output = run_filter(
        tmp_path,
        """
        <html>
          <body>
            <form id="dangerous" action="java&#x73;cript:alert(1)" method="post">
              <input name="q" value="term">
              <button formaction=" JAVASCRIPT:alert(2) ">Submit</button>
            </form>
            <form id="safe" action="/search" method="get">
              <button formaction="/export">Export</button>
            </form>
          </body>
        </html>
        """,
    )
    soup = parse_fragment(output)

    dangerous = soup.find("form", id="dangerous")
    assert dangerous is not None
    assert dangerous.get("method") == "post"
    assert not dangerous.has_attr("action")
    assert not dangerous.find("button").has_attr("formaction")

    safe = soup.find("form", id="safe")
    assert safe is not None
    assert safe.get("action") == "/search"
    assert safe.find("button").get("formaction") == "/export"


def test_encoded_protocols_and_dangerous_styles_are_removed_without_dropping_safe_attributes(tmp_path):
    output = run_filter(
        tmp_path,
        """
        <html>
          <body>
            <a href="jav&#x61;\nscript:alert(1)">bad href</a>
            <div style="background:url(javascript:alert(1))">bad style</div>
            <p style="color: red; font-weight: bold">safe style</p>
            <img src="data:image/png;base64,AAAA" alt="logo">
            <math display="block"><msup><mi>a</mi><mn>2</mn></msup></math>
          </body>
        </html>
        """,
    )
    soup = parse_fragment(output)

    bad_link = soup.find("a")
    assert bad_link is not None
    assert not bad_link.has_attr("href")

    bad_div = soup.find("div")
    assert bad_div is not None
    assert not bad_div.has_attr("style")

    safe_p = soup.find("p")
    assert safe_p is not None
    assert safe_p.get("style") == "color: red; font-weight: bold"

    img = soup.find("img")
    assert img is not None
    assert img.get("src") == "data:image/png;base64,AAAA"
    assert soup.find("math") is not None
