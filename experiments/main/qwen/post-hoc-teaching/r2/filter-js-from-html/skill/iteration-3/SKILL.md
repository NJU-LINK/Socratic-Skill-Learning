---
name: filter-js-from-html
description: >
  Remove executable JavaScript behavior from HTML files while preserving
  legitimate document structure, visible content, SVG graphics, MathML
  equations, forms, links, and non-dangerous attributes. Handles adversarial
  inputs including encoded payloads, null-byte obfuscation, case variation,
  SVG/MathML-specific vectors, and malformed markup.
---

# Filter JavaScript from HTML

## Goal

Create a Python script (`/app/filter.py`) that takes an HTML file path as `argv[1]`,
removes all executable JavaScript behavior, and writes the sanitized HTML back
to the same file **in-place**.

## Environment

- Python 3.13+ with `beautifulsoup4` (and optionally `html5lib`, `lxml`)
- Chromium available for Selenium-based test verification
- The script must handle both full HTML documents and fragments

## Architecture

The filter operates in a pipeline:

```
Raw HTML → Pre-process → Parse → Sanitize Tree → Serialize → Post-process → Write
```

### Step 1: Pre-processing

Remove **null bytes** (`\x00`) from the raw HTML before parsing. Browsers silently
strip null bytes from tag names and attribute names, so `<scr\0ipt>` is interpreted
as `<script>` by the browser. Python's HTML parsers do NOT do this, so we must
pre-process.

```python
content = html_content.replace('\x00', '')
```

### Step 2: Parsing

Use **BeautifulSoup with html5lib** parser for best fidelity:
- Preserves SVG/MathML attribute case (e.g., `viewBox`, `preserveAspectRatio`)
- Follows HTML5 parsing spec for malformed markup
- Handles namespace-aware SVG and MathML elements

For **fragments** (input without `<!DOCTYPE` or `<html>`), extract `body.decode_contents()`
after sanitization to avoid adding wrapper elements.

### Step 3: Tree Sanitization

Walk the parsed DOM tree and apply these transformations:

#### 3a. Remove entirely dangerous elements

These tags can load/execute external content and must be removed completely:

| Tag | Reason |
|-----|--------|
| `script` | Direct script execution |
| `iframe` | Loads external content, can execute scripts |
| `object` | Embeds executable content |
| `embed` | Embeds executable content |
| `applet` | Java applets (deprecated) |
| `base` | Redirects relative URL resolution |
| `portal` | Loads external pages |
| `isindex` | Deprecated form element |
| `foreignObject` / `foreignobject` | Can embed full HTML documents with `<body onload>` and other dangerous constructs; even after sanitizing contents, the container itself is a known XSS vector. Note: html5lib preserves the camelCase `foreignObject`, so check for both cases |

Also remove `<meta http-equiv="refresh">` (navigation-based execution).

#### 3b. Remove event handler attributes from ALL elements

Any attribute starting with `on` (case-insensitive) is an event handler:
`onclick`, `onload`, `onerror`, `onmouseover`, `onfocus`, `onbegin`, `onend`,
`ontoggle`, `onbounce`, etc.

```python
def is_event_handler(attr_name):
    return attr_name.lower().startswith('on')
```

This covers SVG animation events (`onbegin`, `onend`, `onrepeat`),
MathML events, standard DOM events, and any custom `on*` handlers.

#### 3c. Neutralize dangerous URLs

Check all URL-bearing attributes for dangerous protocols:

**URL attributes to check:** `href`, `src`, `action`, `formaction`, `data`,
`poster`, `background`, `dynsrc`, `lowsrc`, `codebase`, `classid`,
`usemap`, `longdesc`, `xlink:href`, `manifest`

**Dangerous protocols:** `javascript:`, `vbscript:`, `livescript:`

**Dangerous data: MIME types:** `text/html`, `application/xhtml+xml`,
`image/svg+xml`, `text/xml`, `application/xml`

**URL normalization before checking:**
1. Strip whitespace and control characters (`\x00`-`\x20`, `\x7f`, `\xa0`)
2. Decode HTML entities (`html.unescape()`) — handles `&#106;avascript:`
3. Percent-decode (`urllib.parse.unquote()`) — handles `%6Aavascript:`
4. Iterate steps 1-3 until the value stabilizes (handles layered encodings like `%256A%2561...` or `&#37;6A...`)
5. Lowercase for protocol comparison

```python
from urllib.parse import unquote

def normalize_url(raw_value):
    """Fully normalize a URL value for protocol checking.
    Iterates stripping, entity-decoding, and percent-decoding until stable."""
    prev = None
    value = raw_value
    while value != prev:
        prev = value
        # Strip whitespace/control chars
        value = re.sub(r'[\x00-\x20\x7f\xa0]+', '', value)
        # Decode HTML entities
        value = html.unescape(value)
        # Percent-decode
        value = unquote(value)
    return value.lower()

def is_dangerous_url(raw_value):
    if not raw_value:
        return False
    if isinstance(raw_value, list):
        raw_value = ' '.join(str(v) for v in raw_value)
    if not isinstance(raw_value, str):
        return False
    
    lower = normalize_url(raw_value)
    if lower.startswith(('javascript:', 'vbscript:', 'livescript:')):
        return True
    if lower.startswith('data:'):
        mime_match = re.match(r'data:\s*([^;,]+)', lower)
        if mime_match and mime_match.group(1).strip() in DANGEROUS_DATA_MIMES:
            return True
    return False
```

#### 3d. Handle SVG-specific vectors

- **`<use>` with external references**: Remove `href`/`xlink:href` if not
  starting with `#` (internal refs are safe)
- **SVG animation elements** (`<animate>`, `<set>`, `<animateTransform>`):
  - Remove event handler attributes (`onbegin`, `onend`, etc.)
  - **Deferred mutation**: Check `attributeName` — if it targets an event handler
    or URL-bearing attribute, remove the animation element entirely. SMIL animations
    can modify other elements' attributes after page load, turning safe markup into
    dangerous markup. Example: `<set attributeName="onerror" to="alert(1)"/>` injects
    an event handler; `<set attributeName="href" to="javascript:..."/>` injects a
    dangerous URL. Both must be removed even though the animation element itself has
    no dangerous attributes.

#### 3e. Clean dangerous HTML comments

Remove comments containing script-like content, javascript: URLs, or event handlers.

#### 3f. Sanitize CSS style attributes

Check `style` attribute values for dangerous URLs. While `javascript:` in CSS `url()` doesn't execute in modern Chromium, remove the entire `style` attribute if it contains dangerous protocols as a security-first measure.

```python
def sanitize_style_attribute(tag):
    """Remove style attributes containing dangerous URLs."""
    style = tag.get('style', '')
    if not style:
        return
    
    # Check for dangerous protocols in the style value
    if is_dangerous_url(style):
        del tag.attrs['style']
        return
    
    # Also check for url() with dangerous protocols
    # Match url(...) patterns and check each one
    url_pattern = re.compile(r'url\s*\(\s*["\']?([^"\')]+)["\']?\s*\)', re.IGNORECASE)
    for match in url_pattern.finditer(style):
        url_value = match.group(1)
        if is_dangerous_url(url_value):
            del tag.attrs['style']
            return
```

This preserves safe styles like `color: red` or `background: url(image.png)` while removing styles with `javascript:` URLs.

**Integration**: Call `sanitize_style_attribute(tag)` during the tag sanitization phase (Step 3b/3c), alongside event handler and URL attribute removal.

### Step 4: Post-processing

Restore SVG camelCase attribute names if the parser lowercased them:
`viewbox` → `viewBox`, `preserveaspectratio` → `preserveAspectRatio`, etc.

## Key Design Decisions

1. **html5lib over html.parser**: html5lib preserves SVG attribute case and
   follows the HTML5 spec more closely. The trade-off is adding wrappers to
   fragments, which we handle by detecting fragments and extracting body content.

2. **Remove entire elements vs. sanitize contents**: For `script`, `iframe`,
   `object`, `embed` — remove entirely. For SVG, MathML, forms — sanitize
   contents but preserve structure.

3. **Conservative URL checking**: Decode entities and strip whitespace before
   checking protocols, because browsers do the same normalization.

4. **Style attributes sanitized for dangerous URLs**: While `javascript:` in CSS `url()` does NOT execute in modern Chromium, the sanitizer removes `style` attributes containing `javascript:` or other dangerous protocols as a security-first measure. Safe styles (`color: red`, `background: url(image.png)`) are preserved. Check style attribute values for dangerous protocols using the same normalization as URL attributes.

5. **data: URL selectivity**: Only flag `data:` URLs with MIME types that can
   execute scripts (`text/html`, `image/svg+xml`, etc.). Safe image types
   (`image/png`, `image/jpeg`) are preserved.

6. **Static vs. deferred danger**: The filter must handle two categories:
   (a) **Static danger** — elements/attributes that are dangerous right now
   (script tags, on* handlers, javascript: URLs); (b) **Deferred/mutating
   danger** — elements that will modify other elements after page load
   (SMIL animations targeting dangerous attributes). Both must be neutralized.

## Common Pitfalls

- **Null bytes in tag names**: `<scr\0ipt>` → browsers see `<script>`, Python
  parsers don't. Must pre-process.
- **Entity-encoded URLs**: `<a href="&#106;avascript:...">` → browser decodes
  entities before URL processing. Must decode before checking.
- **Whitespace in protocols**: `java\tscript:` → browsers strip whitespace.
  Must normalize before checking.
- **SVG attribute case**: `viewBox` is case-sensitive in SVG. HTML parsers
  may lowercase it, breaking rendering.
- **Fragment detection**: html5lib adds `<html><head></head><body>` wrappers
  to fragments. Must detect and strip for fragment inputs.
- **formaction on buttons/inputs**: `<button formaction="javascript:...">`
  is as dangerous as `<form action="javascript:...">`.
- **Deferred mutation via SMIL**: SVG animations (`<animate>`, `<set>`) can
  modify attributes on other elements after page load. An animation with
  `attributeName="onerror"` or `attributeName="href"` can inject dangerous
  content dynamically. Must check what attributes animations target, not just
  whether the animation element itself has dangerous attributes.
- **foreignObject is a dangerous container**: `<foreignObject>` can embed full HTML documents with `<body onload="...">` and other constructs. Even after sanitizing the contents, the foreignObject itself is a known XSS vector. Remove it entirely, don't just sanitize contents. Note: html5lib preserves the camelCase `foreignObject`, so check for both `foreignobject` and `foreignObject` when removing.
- **CSS style attributes with javascript: URLs**: Even though `javascript:` in CSS `url()` doesn't execute in modern Chromium, remove `style` attributes containing dangerous protocols as a security-first measure. Other browsers or older versions may execute them.
- **Percent-encoded URLs**: `%6Aavascript:alert(1)` is equivalent to `javascript:alert(1)` after browser URL decoding. Must percent-decode as part of URL normalization.
- **Layered encodings**: Attackers may combine entity encoding and percent encoding in multiple layers: `&#37;6Aavascript:` (entity `%` → percent-decode → `javascript:`), or `%256A%2561...` (double percent-encoding). The normalization must iterate until the value stabilizes.

## Dependencies

```
beautifulsoup4>=4.12
html5lib>=1.1
```

Install if needed: `pip install beautifulsoup4 html5lib`
