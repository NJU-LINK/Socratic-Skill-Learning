import subprocess
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup


FILTER = Path("/app/filter.py")


def run_filter(html_text: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        html_path = Path(tmpdir) / "sample.html"
        html_path.write_text(html_text, encoding="utf-8")
        subprocess.run(["python3", str(FILTER), str(html_path)], check=True)
        return html_path.read_text(encoding="utf-8")


def parse(html_text: str) -> BeautifulSoup:
    return BeautifulSoup(html_text, "html.parser")


def test_sanitizes_fragmented_javascript_and_preserves_safe_navigation():
    output = run_filter(
        """
        <!doctype html>
        <html>
          <body>
            <a id="bad" href="java&#x73;\ncript:alert(1)" title="kept">Bad</a>
            <a id="good" href="/docs?x=1#frag" class="nav">Docs</a>
          </body>
        </html>
        """
    )

    soup = parse(output)
    bad = soup.find(id="bad")
    good = soup.find(id="good")

    assert bad is not None
    assert bad.get("href") is None
    assert bad.get("title") == "kept"
    assert good is not None
    assert good.get("href") == "/docs?x=1#frag"
    assert good.get("class") == ["nav"]


def test_removes_event_handlers_dangerous_form_targets_and_dangerous_style_only():
    output = run_filter(
        """
        <div class="card" onclick="alert(1)" data-id="7" style="color: red">
          <form action="/submit" method="post">
            <button id="send" formaction="java&#115;cript:alert(1)">Send</button>
          </form>
          <a id="safe-link" href="/home" style="background: #fff">Home</a>
          <a id="styled-bad" href="/ok" style="background-image: url(javascript:alert(1))">Oops</a>
        </div>
        """
    )

    soup = parse(output)
    card = soup.find("div", class_="card")
    send = soup.find(id="send")
    safe_link = soup.find(id="safe-link")
    styled_bad = soup.find(id="styled-bad")

    assert card is not None
    assert card.get("onclick") is None
    assert card.get("data-id") == "7"
    assert card.get("style") == "color: red"
    assert send is not None
    assert send.get("formaction") is None
    assert soup.form.get("action") == "/submit"
    assert safe_link.get("style") == "background: #fff"
    assert styled_bad.get("style") is None


def test_removes_active_containers_refresh_and_sanitizes_template_content():
    output = run_filter(
        """
        <html><head>
          <meta http-equiv="refresh" content="0; url=javascript:alert(1)">
          <script>alert(1)</script>
        </head><body>
          <iframe srcdoc="<script>alert(1)</script>"></iframe>
          <object data="javascript:alert(1)"></object>
          <template id="tpl"><a id="inside-template" href="javascript:alert(1)">X</a></template>
          <p>Visible text</p>
        </body></html>
        """
    )

    soup = parse(output)

    assert soup.find("meta", attrs={"http-equiv": "refresh"}) is None
    assert soup.find("script") is None
    assert soup.find("iframe") is None
    assert soup.find("object") is None
    assert soup.find("p").get_text(strip=True) == "Visible text"

    template = soup.find("template", id="tpl")
    assert template is not None
    inside = template.find("a", id="inside-template")
    assert inside is not None
    assert inside.get("href") is None


def test_preserves_benign_meta_refresh_navigation():
    output = run_filter(
        """
        <html><head>
          <meta http-equiv="refresh" content="5; url=/next?from=landing#section">
        </head><body>
          <p>Continue soon</p>
        </body></html>
        """
    )

    soup = parse(output)
    refresh = soup.find("meta", attrs={"http-equiv": "refresh"})

    assert refresh is not None
    assert refresh.get("content") == "5; url=/next?from=landing#section"
    assert soup.find("p").get_text(strip=True) == "Continue soon"


def test_handles_data_urls_srcset_and_broken_markup_without_dropping_safe_content():
    output = run_filter(
        """
        <html><body>
          <img id="vector" src="data:image/svg+xml,<svg onload=alert(1)></svg>" alt="vector">
          <img id="bitmap" src="data:image/png;base64,AAAA" alt="bitmap">
          <img id="gallery" srcset="javascript:alert(1) 1x, /img/ok.png 2x" src="/img/fallback.png">
          <table><tr><td>Fish &amp; Chips</td><td><a id="ok" href="order.html">Order</a>
        </body></html>
        """
    )

    soup = parse(output)
    vector = soup.find(id="vector")
    bitmap = soup.find(id="bitmap")
    gallery = soup.find(id="gallery")
    ok = soup.find(id="ok")

    assert vector is not None
    assert vector.get("src") is None
    assert vector.get("alt") == "vector"
    assert bitmap is not None
    assert bitmap.get("src") == "data:image/png;base64,AAAA"
    assert gallery is not None
    assert gallery.get("src") == "/img/fallback.png"
    assert gallery.get("srcset") == "/img/ok.png 2x"
    assert ok is not None
    assert ok.get("href") == "order.html"
    assert "Fish & Chips" in soup.get_text(" ", strip=True)
