import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


FILTER = Path("/app/filter.py")
FIXTURES = Path("/app/fixtures")
EXPECTED_SHA256 = {
    "billing-center.html": "20828cbcdcfef813e1d66f294c156f0eaacae1744b5284e1cc3277965c86bea9",
    "dashboard.html": "10873590179329f4ec6562e049fcff95b4db7a71a319223f650a8574a73dec36",
    "docs.html": "4282a11ead0f26e53a936e914bbb51db186b54a8fc8b01a4d987c76c056deab0",
    "intake-form.html": "ebb3f1b76816f0742a5547d2281166b15d59663a5124963e6bcca6a52143eef7",
    "partner-portal.html": "d17632d3de2ab48859f1e51c6f8c7ddcb233d317b6a30fddfc763973fe4a28be",
    "release-notes.html": "10c5a0429be3dd43ba0de12a4552a1a8a876656731ebe35d9f5707c0e14ee6ba",
}


def run_filter(path: Path) -> bytes:
    assert FILTER.is_file(), "/app/filter.py was not created"
    subprocess.run(["python3", str(FILTER), str(path)], check=True)
    return path.read_bytes()


@pytest.mark.parametrize("name", sorted(EXPECTED_SHA256))
def test_realistic_tainted_fixture_matches_private_clean_digest(name: str, tmp_path: Path):
    target = tmp_path / name
    shutil.copyfile(FIXTURES / name, target)
    output = run_filter(target)
    assert hashlib.sha256(output).hexdigest() == EXPECTED_SHA256[name]


def test_clean_document_is_preserved_verbatim():
    safe = b"""<!DOCTYPE html>
<html>
<body>
  <main>
    <a href="/reports" data-track="csv">Export</a>
    <button type="submit" formaction="/submit">Send</button>
    <iframe class="preview" sandbox="allow-same-origin" srcdoc="&lt;section&gt;&lt;p&gt;Preview&lt;/p&gt;&lt;/section&gt;"></iframe>
    <template id="tmpl"><img src="/assets/logo.png"></template>
  </main>
</body>
</html>
"""
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "safe.html"
        path.write_bytes(safe)
        assert run_filter(path) == safe


def test_fresh_obfuscation_is_removed_without_touching_safe_neighbors():
    tainted = (
        b"<div class=\"nav\"><a href=\"  JaVa\tScRiPt:alert(1)\" data-id=\"keep\">Docs</a> "
        b"<img src=\"logo.png\" o&#x6E;error=\"alert(2)\">"
        b"<button formaction=\"data:text/html,%3Cscript%3Eboom%3C/script%3E\" "
        b"type=\"submit\">Go</button></div>\n"
    )
    expected = (
        b"<div class=\"nav\"><a data-id=\"keep\">Docs</a> "
        b"<img src=\"logo.png\"><button type=\"submit\">Go</button></div>\n"
    )
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "fresh.html"
        path.write_bytes(tainted)
        assert run_filter(path) == expected
