import subprocess
import sys
import tempfile
from pathlib import Path


FILTER = Path("/app/filter.py")


def run_filter(html_text: str) -> str:
    with tempfile.TemporaryDirectory() as temporary:
        html_path = Path(temporary) / "sample.html"
        html_path.write_text(html_text, encoding="utf-8")
        subprocess.run([sys.executable, str(FILTER), str(html_path)], check=True)
        return html_path.read_text(encoding="utf-8")


def test_filter_script_exists():
    assert FILTER.exists(), "/app/filter.py was not created"


def test_clean_html_is_unchanged():
    original = (
        "<!doctype html>\n"
        "<html><body><nav class='top'><a href='https://example.com?q=1&amp;x=2'>Go</a>"
        "<form method='post' action='/submit'><input name='q' value='ok'></form>"
        "<table data-kind='report'><tr><td>Safe &amp; sound</td></tr></table></nav></body></html>\n"
    )
    assert run_filter(original) == original


def test_duplicate_href_with_encoded_javascript_is_neutralized():
    dirty = (
        "<html><head><title>clean</title></head><body>"
        "<a id='dup' class='keep' href='https://example.com' "
        "href='java&#x73;cript:document.title=\"pwned\"'>click</a>"
        "</body></html>"
    )
    cleaned = run_filter(dirty)
    assert "class='keep'" in cleaned or 'class="keep"' in cleaned
    assert "javascript:" not in cleaned.lower()
    assert "href='https://example.com'" in cleaned or 'href="https://example.com"' in cleaned
    assert "click</a>" in cleaned


def test_malformed_event_handler_and_script_block_are_removed():
    dirty = (
        "<html><head><title>safe</title><ScRiPt>document.title='pwned'</ScRiPt></head>"
        "<body><img alt='x' src='missing.png' onerror = \"document.title='boom'\"//>"
        "<p data-note='ok'>hello</p></body></html>"
    )
    cleaned = run_filter(dirty)
    assert "script" not in cleaned.lower()
    assert "onerror" not in cleaned.lower()
    assert "data-note='ok'" in cleaned or 'data-note="ok"' in cleaned
    assert "<title>safe</title>" in cleaned.lower()
    assert "<p data-note='ok'>hello</p>" in cleaned or '<p data-note="ok">hello</p>' in cleaned


def test_meta_refresh_and_srcdoc_payloads_are_removed_but_safe_text_remains():
    dirty = (
        "<html><head><title>stay</title>"
        "<meta http-equiv='refresh' content='0; url=java%73cript:document.title=1'>"
        "</head><body><iframe srcdoc='<script>document.title=2</script>'></iframe>"
        "<div id='keep'>visible</div></body></html>"
    )
    cleaned = run_filter(dirty)
    lowered = cleaned.lower()
    assert "http-equiv" not in lowered
    assert "srcdoc" not in lowered
    assert "visible" in cleaned
    assert "<title>stay</title>" in lowered


def test_fragmented_javascript_form_action_is_removed_but_form_stays():
    dirty = (
        "<form id='f' method='post' class='checkout' "
        "formaction='java%0d%0ascript:alert(1)' action='/pay'>"
        "<button type='submit'>Send</button></form>"
    )
    cleaned = run_filter(dirty)
    lowered = cleaned.lower()
    assert "formaction" not in lowered
    assert "action='/pay'" in cleaned or 'action="/pay"' in cleaned
    assert "class='checkout'" in cleaned or 'class="checkout"' in cleaned
    assert "<button type='submit'>send</button>" in lowered


def test_dangerous_srcset_is_removed_while_safe_src_survives():
    dirty = (
        "<picture><source media='(min-width: 700px)' "
        "srcset='java&#x73;cript:alert(1) 1x, /img/hero@2x.png 2x'>"
        "<img alt='hero' src='safe.png' srcset='/img/hero.png 1x, /img/hero@2x.png 2x'></picture>"
    )
    cleaned = run_filter(dirty)
    assert "javascript:" not in cleaned.lower()
    assert "<img alt='hero' src='safe.png'" in cleaned or '<img alt="hero" src="safe.png"' in cleaned
    assert "/img/hero.png 1x, /img/hero@2x.png 2x" in cleaned
    assert "media='(min-width: 700px)'" in cleaned or 'media="(min-width: 700px)"' in cleaned
