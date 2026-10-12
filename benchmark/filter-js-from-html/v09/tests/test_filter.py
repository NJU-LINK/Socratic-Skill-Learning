import html
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path


FILTER = Path("/app/filter.py")
REQUIRED_SAMPLES = ("landing-page.html", "dashboard.html")


def resolve_samples_dir() -> Path:
    here = Path(__file__).resolve()
    candidates = [Path("/app/samples"), here.parent.parent / "samples"]
    if len(here.parents) > 2:
        root = here.parents[2]
        candidates.extend([
            root / "samples",
            root / "input" / "samples",
            root / "build01_v09_output" / "samples",
        ])
    for candidate in candidates:
        if all((candidate / sample).is_file() for sample in REQUIRED_SAMPLES):
            return candidate
    raise FileNotFoundError("Could not locate required sample HTML files")


SAMPLES = resolve_samples_dir()


class TagCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def parse_html(document: str) -> TagCollector:
    parser = TagCollector()
    parser.feed(document)
    return parser


def find_tag(parser: TagCollector, tag_name: str, **attrs):
    for tag, tag_attrs in parser.tags:
        if tag != tag_name:
            continue
        if all(tag_attrs.get(key) == value for key, value in attrs.items()):
            return tag_attrs
    return None


def run_filter(tmp_path: Path, source: Path) -> str:
    target = tmp_path / source.name
    shutil.copy(source, target)
    subprocess.run(["python3", str(FILTER), str(target)], check=True)
    return target.read_text(encoding="utf-8")


def test_clean_html_remains_unchanged(tmp_path: Path) -> None:
    clean_html = """<!DOCTYPE html>
<html lang=\"en\">
<body class=\"page\" data-view=\"clean\" aria-live=\"polite\">
  <nav class=\"cluster\" data-nav=\"main\"><a href=\"/pricing\">Pricing</a></nav>
  <section class=\"card\" style=\"display:grid;gap:1rem;background:#fff;\">Safe content</section>
</body>
</html>
"""
    target = tmp_path / "clean.html"
    target.write_text(clean_html, encoding="utf-8")

    subprocess.run(["python3", str(FILTER), str(target)], check=True)

    assert target.read_text(encoding="utf-8") == clean_html


def test_landing_page_keeps_safe_attributes_while_cleaning_nested_payloads(tmp_path: Path) -> None:
    sanitized = run_filter(tmp_path, SAMPLES / "landing-page.html")
    parser = parse_html(sanitized)

    iframe = find_tag(parser, "iframe", **{"class": "preview-frame rounded shadow-sm"})
    assert iframe is not None
    assert iframe["data-owner"] == "creative-ops"
    assert iframe["data-theme"] == "sand"
    assert iframe["width"] == "640"
    assert iframe["height"] == "240"

    srcdoc = html.unescape(iframe["srcdoc"])
    assert "javascript:" not in srcdoc.lower()
    assert "launch week" in srcdoc.lower()
    assert "keep this preview text and classes intact." in srcdoc.lower()
    assert "data-preview='campaign'" in srcdoc or 'data-preview="campaign"' in srcdoc
    assert "font-family:system-ui" in srcdoc

    promo_band = find_tag(parser, "article", **{"data-module": "seasonal-banner"})
    assert promo_band is not None
    assert "expression(" not in promo_band["style"].lower()
    assert "linear-gradient" in promo_band["style"]
    assert promo_band["data-priority"] == "high"
    assert "Spring launch toolkit" in sanitized


def test_dashboard_keeps_forms_and_tracking_metadata(tmp_path: Path) -> None:
    sanitized = run_filter(tmp_path, SAMPLES / "dashboard.html")
    parser = parse_html(sanitized)

    button = find_tag(parser, "button", **{"data-audit": "workspace-review"})
    assert button is not None
    assert button["class"] == "button button-secondary"
    assert button["data-owner"] == "ops-queue"
    assert button["data-audit"] == "workspace-review"
    assert button.get("formaction", "") == ""
    assert "Open review queue" in sanitized

    banner = find_tag(parser, "section", **{"data-widget": "status-banner"})
    assert banner is not None
    assert "javascript:" not in banner["style"].lower()
    assert "display:block" in banner["style"]
    assert "border:1px solid #d6deea" in banner["style"]

    form = find_tag(parser, "form", **{"data-form": "workspace-review"})
    assert form is not None
    assert form["action"] == "/workspaces/review"
    assert form["method"] == "post"

    input_tag = find_tag(parser, "input", **{"id": "workspace-slug"})
    assert input_tag is not None
    assert input_tag["value"] == "northwind-core"


def test_active_container_tags_are_removed(tmp_path: Path) -> None:
    html_text = """<!DOCTYPE html>
<html><body>
  <div class=\"shell\" data-card=\"demo\">before<object data=\"movie.swf\" width=\"320\" height=\"180\"></object><embed src=\"movie.swf\" type=\"application/x-shockwave-flash\">after</div>
</body></html>
"""
    target = tmp_path / "containers.html"
    target.write_text(html_text, encoding="utf-8")

    subprocess.run(["python3", str(FILTER), str(target)], check=True)

    sanitized = target.read_text(encoding="utf-8")
    parser = parse_html(sanitized)
    assert find_tag(parser, "object") is None
    assert find_tag(parser, "embed") is None
    assert "beforeafter" in sanitized.replace("\n", "").replace("  ", "")
    assert 'class="shell"' in sanitized
    assert 'data-card="demo"' in sanitized
