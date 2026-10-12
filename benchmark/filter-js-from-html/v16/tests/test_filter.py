import subprocess
import textwrap
from html.parser import HTMLParser
from pathlib import Path


class Node:
    def __init__(self, tag: str, attrs: dict[str, str], parent: "Node | None") -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[Node] = []
        self.text_parts: list[str] = []

    def text_content(self) -> str:
        parts = [piece for piece in self.text_parts]
        for child in self.children:
            child_text = child.text_content()
            if child_text:
                parts.append(child_text)
        return " ".join(part for part in parts if part).strip()


class TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("__root__", {}, None)
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs) -> None:
        node = Node(tag, {name: value if value is not None else "" for name, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        self.stack.append(node)

    def handle_startendtag(self, tag, attrs) -> None:
        node = Node(tag, {name: value if value is not None else "" for name, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data) -> None:
        text = data.strip()
        if text:
            self.stack[-1].text_parts.append(text)


def parse_html(text: str) -> Node:
    parser = TreeBuilder()
    parser.feed(text)
    parser.close()
    return parser.root


def find_first(node: Node, tag: str, **attrs: str) -> Node | None:
    for child in node.children:
        if child.tag == tag and all(child.attrs.get(name) == value for name, value in attrs.items()):
            return child
        match = find_first(child, tag, **attrs)
        if match is not None:
            return match
    return None


def run_filter(tmp_path: Path, html_text: str) -> tuple[str, Node]:
    html_file = tmp_path / "page.html"
    html_file.write_text(textwrap.dedent(html_text), encoding="utf-8")
    subprocess.run(["python3", "/app/filter.py", str(html_file)], check=True)
    rendered = html_file.read_text(encoding="utf-8")
    return rendered, parse_html(rendered)


def normalize_html(text: str) -> str:
    return "\n".join(line.rstrip() for line in textwrap.dedent(text).strip().splitlines())


def test_removes_only_unsafe_attributes_from_dense_markup(tmp_path: Path) -> None:
    rendered, root = run_filter(
        tmp_path,
        """
        <!doctype html>
        <html lang="en">
          <body>
            <section id="hero" class="hero grid xl" data-layout="marketing" aria-labelledby="headline"
                     style="display:grid; gap:1rem; width:calc(100% - 2rem); x:expression(alert(1)); color:#123456">
              <h1 id="headline">Launch week</h1>
              <a id="cta" class="btn primary" data-track="hero-cta" aria-label="Request a demo"
                 title="Book a demo" href=" \n JaVaScRiPt:\talert(1) " onclick="trackClick()">Book a demo</a>
              <iframe id="embed" class="frame shell" data-slot="promo" title="Preview"
                      sandbox="allow-forms allow-same-origin" srcdoc="<script>alert(1)</script><p>owned</p>"></iframe>
            </section>
          </body>
        </html>
        """,
    )

    hero = find_first(root, "section", id="hero")
    assert hero is not None
    style = hero.attrs["style"]
    assert "display:grid" in style
    assert "gap:1rem" in style
    assert "width:calc(100% - 2rem)" in style
    assert "color:#123456" in style
    assert "expression" not in style.lower()
    assert hero.attrs["data-layout"] == "marketing"
    assert hero.attrs["aria-labelledby"] == "headline"

    cta = find_first(root, "a", id="cta")
    assert cta is not None
    assert cta.text_content() == "Book a demo"
    assert cta.attrs.get("href") is None
    assert cta.attrs.get("onclick") is None
    assert cta.attrs["class"] == "btn primary"
    assert cta.attrs["data-track"] == "hero-cta"
    assert cta.attrs["aria-label"] == "Request a demo"
    assert cta.attrs["title"] == "Book a demo"

    assert find_first(root, "iframe", id="embed") is None
    assert "owned" not in rendered
    assert 'data-slot="promo"' not in rendered


def test_neutralizes_navigation_vectors_without_breaking_safe_form_markup(tmp_path: Path) -> None:
    _, root = run_filter(
        tmp_path,
        """
        <html>
          <head>
            <meta charset="utf-8">
            <meta http-equiv="refresh" content="0; URL= javascript:alert('owned') ">
          </head>
          <body>
            <form id="signup" class="stack compact" method="post" action="/subscribe" data-flow="trial">
              <input type="email" name="email" autocomplete="email" aria-label="Work email">
              <button type="submit" class="btn accent" data-variant="primary"
                      formaction="data:text/html,%3Cscript%3Ealert(1)%3C/script%3E">Start trial</button>
            </form>
            <a id="docs" href="/docs/getting-started" rel="noopener" data-topic="docs">Docs</a>
          </body>
        </html>
        """,
    )

    refresh = find_first(root, "meta", **{"http-equiv": "refresh"})
    assert refresh is not None
    assert refresh.attrs.get("content") is None

    form = find_first(root, "form", id="signup")
    assert form is not None
    assert form.attrs["action"] == "/subscribe"
    assert form.attrs["method"] == "post"
    assert form.attrs["class"] == "stack compact"
    assert form.attrs["data-flow"] == "trial"

    button = find_first(form, "button")
    assert button is not None
    assert button.text_content() == "Start trial"
    assert button.attrs.get("formaction") is None
    assert button.attrs["class"] == "btn accent"
    assert button.attrs["data-variant"] == "primary"

    docs = find_first(root, "a", id="docs")
    assert docs is not None
    assert docs.attrs["href"] == "/docs/getting-started"
    assert docs.attrs["rel"] == "noopener"
    assert docs.attrs["data-topic"] == "docs"


def test_removes_script_tags_and_svg_javascript_urls_but_keeps_other_content(tmp_path: Path) -> None:
    rendered, root = run_filter(
        tmp_path,
        """
        <html>
          <body>
            <table class="pricing" data-region="us" aria-describedby="pricing-note">
              <tr>
                <td>
                  <svg viewBox="0 0 20 20" role="img" aria-label="Brand mark">
                    <a xlink:href="javascript:alert(1)" target="_blank"><text x="1" y="14">Logo</text></a>
                  </svg>
                </td>
                <td id="pricing-note">Quarterly billing available</td>
              </tr>
            </table>
            <script>console.log('remove me')</script>
          </body>
        </html>
        """,
    )

    assert "<script" not in rendered.lower()

    table = find_first(root, "table", **{"class": "pricing"})
    assert table is not None
    assert table.attrs["data-region"] == "us"
    assert table.attrs["aria-describedby"] == "pricing-note"
    assert "Quarterly billing available" in table.text_content()

    link = find_first(root, "a")
    assert link is not None
    assert link.attrs.get("xlink:href") is None
    assert link.attrs["target"] == "_blank"
    assert link.text_content() == "Logo"


def test_removes_active_container_tags_and_executable_payloads(tmp_path: Path) -> None:
    rendered, root = run_filter(
        tmp_path,
        """
        <html>
          <body>
            <div class="layout" data-zone="media">
              <object id="brochure" data="/promo/interactive.html" type="text/html" aria-label="Brochure viewer">
                <p>fallback brochure copy</p>
              </object>
              <embed id="teaser" src="data:text/html,%3Cscript%3Ealert(1)%3C/script%3E" type="text/html" title="Teaser embed">
              <iframe id="map" src="/maps/embed.html" title="Store map" loading="lazy"></iframe>
              <p id="summary">Locations and amenities</p>
            </div>
          </body>
        </html>
        """,
    )

    assert find_first(root, "object", id="brochure") is None
    assert find_first(root, "embed", id="teaser") is None
    assert find_first(root, "iframe", id="map") is None
    assert 'data-zone="media"' in rendered
    assert 'id="summary"' in rendered
    assert "Locations and amenities" in rendered
    assert "fallback brochure copy" not in rendered


def test_safe_dense_document_remains_byte_stable(tmp_path: Path) -> None:
    source = """
    <!doctype html>
    <html lang="en">
      <body>
        <section class="hero grid" data-theme="spring" aria-labelledby="hero-title">
          <img src="/assets/hero.png" alt="Team celebrating launch" title="Launch banner" width="640" height="320">
          <a href="/pricing?plan=pro&amp;cycle=annual" class="btn primary" data-track="pricing">See pricing</a>
          <form action="/signup" method="post" class="signup" data-flow="trial">
            <input type="email" name="email" autocomplete="email" aria-label="Email">
            <button type="submit" formaction="/signup/confirm" class="cta">Start now</button>
          </form>
        </section>
      </body>
    </html>
    """

    rendered, _ = run_filter(tmp_path, source)

    assert normalize_html(rendered) == normalize_html(source)
