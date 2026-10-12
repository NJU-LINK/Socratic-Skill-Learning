---
name: filter-js-from-html
description: >
  Remove executable JavaScript behavior from HTML files while preserving
  legitimate document structure, visible content, vector graphics, equations,
  forms, links, and non-dangerous attributes. Uses namespace-aware HTML5
  parsing to handle SVG, MathML, and cross-namespace attack vectors.
---

# Filter JavaScript from HTML

## Purpose

Sanitize HTML by removing all executable JavaScript behavior while preserving
safe content. This is a security-critical operation that must handle:

- Direct script execution (`<script>`, event handlers, `javascript:` URLs)
- SVG-specific vectors (`<script>` in SVG, `<animate>` attribute mutation, `<foreignObject>`, `<handler>`, `<use>` with dangerous hrefs)
- MathML-specific vectors (`<annotation-xml>` with HTML encoding)
- Obfuscated payloads (mixed case, whitespace injection, entity encoding, null bytes)
- CSS-based execution (`expression()`, `url(javascript:)`, `-moz-binding`, `behavior:`)
- Navigation-based execution (`<meta http-equiv="refresh">` with JS URLs, `<base>` tag manipulation)
- Parser mismatch attacks (noscript mXSS)

## Architecture

**Parse → Walk → Sanitize → Serialize** using `html5lib` with `namespaceHTMLElements=True`.

### Why html5lib?

HTML parsing is a complex state machine with hundreds of states. Regex cannot replicate browser parsing behavior. Every regex-based sanitizer has known bypasses. `html5lib` is the most spec-compliant HTML5 parser for Python and supports namespace-aware parsing essential for SVG/MathML.

### Namespace-Aware Element Matching

With `namespaceHTMLElements=True`, html5lib uses Clark notation:
- HTML: `{http://www.w3.org/1999/xhtml}tagname`
- SVG: `{http://www.w3.org/2000/svg}tagname`
- MathML: `{http://www.w3.org/1998/Math/MathML}tagname`
- XLink: `{http://www.w3.org/1999/xlink}attrname`

**Critical**: `<script>` inside `<svg>` parses as `{http://www.w3.org/2000/svg}script`, NOT as HTML script. Always check the **local name** (after `}`) to catch dangerous elements in ALL namespaces.

```python
def get_local_name(tag):
    if isinstance(tag, str) and '}' in tag:
        return tag.split('}', 1)[1].lower()
    return (tag or '').lower()

def get_namespace(tag):
    if isinstance(tag, str) and tag.startswith('{'):
        return tag.split('}', 1)[0][1:]
    return None
```

## Danger Taxonomy

### Category A — Remove element and all children

Elements that cause script execution or load external resources unconditionally:

| Element | Reason |
|---------|--------|
| `script` | Direct code execution (any namespace) |
| `iframe`, `frame`, `frameset` | External content loading |
| `object`, `embed`, `applet` | Plugin/external content |
| `base` | URL resolution manipulation |

**SVG-specific removals:**
- `foreignObject` — embeds full HTML document inside SVG
- `handler` — SVG 1.2 event handler element

**SVG animation elements** — remove if `attributeName` targets event handlers or URL attributes:
- `animate`, `animateTransform`, `set` — check `attributeName` for `on*` prefix or URL attribute names

**MathML-specific:**
- `annotation-xml` with `encoding="application/xhtml+xml"` or `encoding="text/html"` — children parsed as HTML

### Category B — Remove attributes on ANY element

- All `on*` event handlers (onclick, onload, onerror, onmouseover, onfocus, onblur, etc.) — 100+ attributes
- `srcdoc` on any element (inline HTML documents)

### Category C — URL-bearing attributes: check for dangerous schemes

Check these attributes for `javascript:`, `vbscript:`, and `data:text/html` schemes:

`href`, `src`, `action`, `formaction`, `data`, `poster`, `background`, `dynsrc`, `lowsrc`, `usemap`, `longdesc`, `ping`, `srcset`, `cite`, `manifest`, `srcdoc`

**XLink namespace**: `xlink:href` in SVG (namespace `http://www.w3.org/1999/xlink`)

**URL normalization**: Strip ALL whitespace (spaces, tabs, newlines), null bytes, HTML entities, and percent-encoding before checking schemes. Browsers ignore whitespace and decode percent-encoding before scheme interpretation.

```python
import urllib.parse

def is_dangerous_url(value):
    if not value:
        return False
    cleaned = re.sub(r'[\s\x00]+', '', value).lower()
    cleaned = re.sub(r'&#x[0-9a-f]+;?', '', cleaned)
    cleaned = re.sub(r'&#\d+;?', '', cleaned)
    cleaned = re.sub(r'&[a-zA-Z]+;', '', cleaned)
    # Iteratively percent-decode (handles layered encoding like %256a -> %6a -> j)
    for _ in range(5):
        try:
            decoded = urllib.parse.unquote(cleaned)
        except Exception:
            decoded = cleaned
        if decoded == cleaned:
            break
        cleaned = decoded
    for scheme in ('javascript:', 'vbscript:', 'data:text/html'):
        if cleaned.startswith(scheme):
            return True
    return False
```

### Category D — Meta refresh

`<meta http-equiv="refresh">` with `content` containing a `javascript:` URL. Extract the URL from `content="seconds;url=URL"` format and check it.

### Category E — CSS sanitization

In `<style>` elements and `style` attributes, neutralize:
- `expression()` — IE CSS expressions
- `url(javascript:...)` — JS in CSS url()
- `behavior:` — IE HTC behaviors
- `-moz-binding:` — Firefox XBL bindings
- `@import url(javascript:...)` — imports with dangerous URLs

### Category F — Noscript mXSS defense

html5lib parses `<noscript>` in scripting-disabled mode (content as HTML). Browsers with JS enabled treat it as raw text. This mismatch can create mXSS.

**Defense**: Inside `<noscript>`, check all text/attributes for `</noscript>` substring. If found, clear the element's content.

## Safe Serialization

Use html5lib's serializer with safety options:

```python
from html5lib import serialize
output = serialize(doc, tree='etree',
    quote_attr_values='always',      # Prevent attribute injection
    omit_optional_tags=False,         # Prevent context confusion
    escape_lt_in_attrs=True,         # Escape < in attribute values
    resolve_entities=True,           # Prevent entity attacks
    sanitize=False)                  # We did our own sanitization
```

**Never use `ElementTree.tostring()`** — it may produce XML-style output that re-parses differently in browsers, creating mXSS.

## Implementation Notes

1. **Comments and PIs**: ElementTree represents comments/PIs with callable tags (not strings). Skip non-string tags during tree walking.
2. **Iteration safety**: When removing children during tree walk, iterate over `list(elem)` (a copy) to avoid modification-during-iteration errors.
3. **Namespace in SVG context**: `<math>` inside `<svg>` gets SVG namespace, not MathML. Local name matching handles this correctly.
4. **Fragment handling**: html5lib always produces a full document tree. Fragments get wrapped in `<html><head></head><body>...</body></html>`.
5. **DOCTYPE**: html5lib drops DOCTYPE during serialization. Functionally equivalent for sanitization purposes.
6. **Tail text preservation**: In ElementTree, every element has a `.tail` property — the text between the element's closing tag and the next sibling. When removing dangerous elements, `parent.remove(elem)` destroys the tail. Transfer tail text to the previous sibling's tail or parent's text before removal:

```python
def _remove_element_preserving_tail(elem, parent):
    tail = elem.tail
    if tail:
        children = list(parent)
        idx = children.index(elem)
        if idx > 0:
            prev = children[idx - 1]
            prev.tail = (prev.tail or '') + tail
        else:
            parent.text = (parent.text or '') + tail
    parent.remove(elem)
```

## Usage

```bash
python3 filter.py <html_file>
```

Modifies the file in-place.

## Dependencies

- Python 3.x
- `html5lib` (`pip install html5lib`)
