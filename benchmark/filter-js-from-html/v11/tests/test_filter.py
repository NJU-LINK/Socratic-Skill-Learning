from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def run_filter(tmp_path: Path, html: str) -> str:
    target = tmp_path / "sample.html"
    target.write_text(textwrap.dedent(html).lstrip(), encoding="utf-8")
    subprocess.run([sys.executable, "/app/filter.py", str(target)], check=True)
    return target.read_text(encoding="utf-8")


def test_preserves_benign_article_markup_exactly(tmp_path: Path) -> None:
    html = """
    <!doctype html>
    <html>
      <body>
        <article class="story" data-id="42">
          <h1>Vector notes</h1>
          <p>Inline math and diagrams should stay untouched.</p>
          <svg viewBox="0 0 10 10" aria-hidden="true">
            <title>Orbit</title>
            <circle cx="5" cy="5" r="4"></circle>
          </svg>
          <math display="block"><mi>x</mi><mo>=</mo><mn>7</mn></math>
          <a href="https://example.com/readmore">Read more</a>
        </article>
      </body>
    </html>
    """

    out = run_filter(tmp_path, html)

    assert out == textwrap.dedent(html).lstrip()


def test_preserves_safe_svg_and_mathml_but_removes_executable_bits(tmp_path: Path) -> None:
    html = """
    <!doctype html>
    <html>
      <body>
        <article class="story">
          <svg viewBox="0 0 10 10" aria-label="diagram">
            <title>Orbit map</title>
            <circle cx="5" cy="5" r="4"></circle>
            <a xlink:href="https://example.com/reference"><text x="1" y="2">ref</text></a>
            <script>alert(1)</script>
            <g onload="alert(2)"><text x="4" y="4">unsafe wrapper</text></g>
          </svg>
          <math display="block">
            <mi>x</mi><mo>=</mo><mn>1</mn>
          </math>
        </article>
      </body>
    </html>
    """

    out = run_filter(tmp_path, html)

    assert "<svg viewBox=\"0 0 10 10\" aria-label=\"diagram\">" in out
    assert "<circle cx=\"5\" cy=\"5\" r=\"4\"></circle>" in out
    assert "xlink:href=\"https://example.com/reference\"" in out
    assert "<math display=\"block\">" in out
    assert "<mi>x</mi><mo>=</mo><mn>1</mn>" in out
    assert "<script" not in out.lower()
    assert "onload=" not in out.lower()
    assert "unsafe wrapper" in out


def test_removes_normalized_javascript_urls_and_meta_refresh(tmp_path: Path) -> None:
    html = """
    <html>
      <head>
        <meta charset="utf-8">
        <meta http-equiv="refresh" content="0; url=javascript:alert(1)">
      </head>
      <body>
        <svg>
          <a xlink:href="&#x6a;ava&#x73;cript:alert(1)"><text>bad entity</text></a>
          <a xlink:href="java%73cript:alert(2)"><text>bad percent</text></a>
          <a xlink:href="https://example.com/good"><text>good</text></a>
        </svg>
        <form action="/submit" formaction="javascript:alert(3)">
          <button type="submit">send</button>
        </form>
      </body>
    </html>
    """

    out = run_filter(tmp_path, html)

    assert "http-equiv" not in out.lower()
    assert "javascript:" not in out.lower()
    assert "&#x6a;ava" not in out.lower()
    assert "java%73cript" not in out.lower()
    assert "xlink:href=\"https://example.com/good\"" in out
    assert "<form action=\"/submit\">" in out
    assert "<button type=\"submit\">send</button>" in out


def test_removes_css_expression_and_dangerous_css_urls_but_keeps_safe_css(tmp_path: Path) -> None:
    html = """
    <article>
      <svg class="icon-set">
        <style>
          text { fill: #333; }
          rect { width: expression(alert(1)); stroke: #000; }
          a { fill: url( java%73cript:alert(2) ); }
        </style>
        <text x="2" y="8" style="color: red; width: expression(alert(3)); background-image: url(&#x6a;avascript:alert(4))">caption</text>
      </svg>
    </article>
    """

    out = run_filter(tmp_path, html)

    assert "expression(" not in out.lower()
    assert "javascript:" not in out.lower()
    assert "java%73cript" not in out.lower()
    assert "&#x6a;avascript" not in out.lower()
    assert "fill: #333;" in out
    assert "stroke: #000;" in out
    assert 'style="color: red"' in out
    assert "caption" in out


def test_strips_multiple_blocked_tag_types_without_touching_surrounding_content(tmp_path: Path) -> None:
    html = """
    <div>
      <p>before</p>
      <iframe src="https://bad.example/embed"></iframe>
      <object data="movie.swf"></object>
      <embed src="clip.svg" />
      <p>after</p>
    </div>
    """

    out = run_filter(tmp_path, html)

    assert "<iframe" not in out.lower()
    assert "<object" not in out.lower()
    assert "<embed" not in out.lower()
    assert "<p>before</p>" in out
    assert "<p>after</p>" in out


def test_removes_malformed_and_obfuscated_script_tag_variants(tmp_path: Path) -> None:
    html = """
    <article>
      <p>alpha</p>
      <ScRiPt>alert(1)</ScRiPt>
      < script >alert(2)</ script >
      <svg><text>diagram</text></svg>
      <p>omega</p>
    </article>
    """
    html = html.replace("<svg>", "<scr\x00ipt>alert(3)</scr\x00ipt><svg>", 1)

    out = run_filter(tmp_path, html)

    assert "alert(1)" not in out
    assert "alert(2)" not in out
    assert "alert(3)" not in out
    assert "script" not in out.lower().replace("description", "")
    assert "<p>alpha</p>" in out
    assert "<svg><text>diagram</text></svg>" in out
    assert "<p>omega</p>" in out


def test_removes_control_character_split_script_tags_inside_mixed_content(tmp_path: Path) -> None:
    html = (
        "<div><math><mi>x</mi></math>"
        "<scr\tipt type=\"text/javascript\">alert(4)</scr\tipt>"
        "<scr\nipt>alert(5)</scr\nipt>"
        "<p>safe tail</p></div>"
    )

    out = run_filter(tmp_path, html)

    assert "alert(4)" not in out
    assert "alert(5)" not in out
    assert "<math><mi>x</mi></math>" in out
    assert "<p>safe tail</p>" in out
