---
name: filter-js-from-html
description: >
  Build a Python script that removes executable JavaScript behavior from HTML files
  while preserving legitimate document structure, visible content, vector graphics,
  equations, forms, links, and non-dangerous attributes. The script takes an HTML file
  path as argv[1], sanitizes it in-place, and handles SVG, MathML, encoding tricks,
  and adversarial payloads.
---

# Filter JavaScript from HTML

## Task Summary

Create `/app/filter.py` — a Python script that:
1. Takes an HTML file path as `argv[1]`
2. Reads the file, removes all executable JavaScript behavior
3. Writes the sanitized HTML back to the same file (in-place modification)
4. Preserves all safe content with minimal alteration

## Architecture

The solution uses a **multi-phase pipeline**:

```
Read file → Parse HTML → Remove dangerous tags → Clean attributes → Regex fallback → Write file
```

### Phase 1: Parse with BeautifulSoup

Use `bs4.BeautifulSoup` with the `html.parser` backend. This gives us:
- Automatic entity decoding in attribute values (handles `&#106;avascript:` → `javascript:`)
- Proper tag/attribute structure recognition
- Handles malformed HTML gracefully

### Phase 2: Remove dangerous container tags entirely

These tags are execution containers — remove them and all their contents:

| Tag | Reason |
|-----|--------|
| `<script>` | Direct script execution |
| `<iframe>` | Can load arbitrary external content with scripts |
| `<object>` | Can execute plugins and load external content |
| `<embed>` | Can execute plugins |
| `<applet>` | Java applet execution |
| `<base>` | Can redirect all relative URLs to attacker-controlled domain |

### Phase 3: Remove dangerous SVG/MathML elements

SVG and MathML can contain executable elements. There are two categories:

#### 3a: Remove entirely (inherently dangerous)

These elements are removed with all their contents because they can dynamically execute or embed arbitrary content:

| Element | Reason |
|---------|--------|
| `<set>` | Can dynamically set attributes (e.g., `xlink:href`) to `javascript:` URLs |
| `<foreignObject>` | Can embed full HTML documents including scripts |
| `<annotation-xml>` | MathML element that can embed foreign executable markup (HTML/SVG) |

#### 3b: Clean attributes (conditionally dangerous)

These SMIL animation elements are **preserved** but their attributes are cleaned in Phase 5:

| Element | Safe usage | Dangerous if... |
|---------|-----------|-----------------|
| `<animate>` | Visual animation (`attributeName`, `values`, `from`, `to`, `dur`) | Has `onbegin`, `onend`, `onrepeat`, `onabort` event handlers or `xlink:href` with `javascript:` |
| `<animateColor>` | Color animation | Has event handlers or dangerous URLs |
| `<animateMotion>` | Motion path animation | Has event handlers or dangerous URLs |
| `<animateTransform>` | Transform animation | Has event handlers or dangerous URLs |

**Important**: BeautifulSoup lowercases tag names with `html.parser`, so search for lowercase versions: `set`, `foreignobject`, `annotation-xml`, `animate`, `animatecolor`, `animatemotion`, `animatetransform`.

### Phase 3c: Sanitize `<style>` element content

`<style>` elements (both HTML and SVG) can contain CSS that executes JavaScript in certain browsers:

```html
<style>body { width: expression(alert(1)); }</style>
<style>div { behavior: url(xss.htc); }</style>
<style>p { -moz-binding: url(xss.xml#xss); }</style>
<style>span { background: url('javascript:alert(1)'); }</style>
```

For each `<style>` tag:
1. Get its text content using `.get_text()` (not `.string`)
2. Apply the same dangerous-CSS regex patterns used for `style` attributes
3. If dangerous patterns are found, remove the entire `<style>` element
4. Safe `<style>` elements (normal CSS rules) are preserved

**Why `.get_text()` instead of `.string`?** BeautifulSoup's `.string` property returns `None` when an element has multiple children (e.g., if the parser creates separate nodes for comments and text). Using `.get_text()` concatenates all descendant text regardless of child structure, eliminating a potential bypass where dangerous CSS could hide after a comment node.

This is a conservative approach — removing the whole element rather than trying to surgically strip individual dangerous declarations, which avoids the complexity of CSS rule parsing.

### Phase 4: Remove meta refresh with dangerous URLs

Check `<meta http-equiv="refresh">` tags. If the `content` attribute contains `url=javascript:...`, remove the entire meta tag. Safe refresh URLs (like `url=https://example.com`) should be preserved.

### Phase 5: Clean attributes on all remaining tags

For every tag in the document, examine each attribute:

#### 5a: Remove event handler attributes (on*)

Any attribute whose name starts with `on` (case-insensitive) is an event handler:
- `onclick`, `onload`, `onerror`, `onmouseover`, `onfocus`, `onblur`, `onsubmit`, etc.
- SVG-specific: `onbegin`, `onend`, `onrepeat`, `onabort`
- Remove the entire attribute, keep the tag and its other attributes.

#### 5b: Remove dangerous URL attributes

Check these URL-bearing attributes for dangerous URL schemes:

**Single-URL attributes**: `href`, `src`, `action`, `formaction`, `data`, `poster`, `dynsrc`, `lowsrc`, `background`, `codebase`, `classid`, `usemap`, `longdesc`, `ping`, `cite`, `manifest`, `xlink:href`, `content`

**Multi-URL attributes**: `srcset` (contains comma-separated URL+descriptor pairs)

Dangerous URL schemes to detect:
- `javascript:` — direct script execution
- `vbscript:` — VBScript execution (IE)
- `data:text/html` — embedded HTML with scripts
- `data:image/svg+xml` — embedded SVG with scripts
- `data:application/xml` or `data:text/xml` — embedded XML with SVG/MathML

#### 5c: Remove dangerous CSS in style attributes

Check `style` attributes for:
- `expression(...)` — IE CSS expression (executes JavaScript)
- `behavior: url(...)` — IE behavior attachment
- `-moz-binding: url(...)` — Firefox XBL binding
- `url('javascript:...')` — JavaScript in CSS URL

Use the same regex pattern as Phase 3c for `<style>` element content. The pattern must handle obfuscation (whitespace/control chars between letters in `javascript:`).

### Phase 6: Regex fallback

After serialization, apply regex to catch any script-like tags that survived parsing due to unusual encoding or malformed markup:
```python
re.sub(r'<\s*/?\s*script\b[^>]*>', '', result, flags=re.IGNORECASE)
```

## Handling Encoding and Obfuscation

### Entity decoding
BeautifulSoup automatically decodes HTML entities in attribute values:
- `&#106;avascript:` → `javascript:` (numeric entities)
- `&#x6A;avascript:` → `javascript:` (hex entities)
- `&amp;#106;avascript:` → `&#106;avascript:` (double encoding — needs second decode)

For double-encoded payloads, apply `html.unescape()` iteratively (up to 3 rounds) before checking URL schemes.

### Whitespace/control character injection
Attackers insert whitespace or control characters between letters:
- `java\tscript:`, `java\nscript:`, `j\x00avascript:`

Use a regex pattern that allows `[\s\x00-\x1f\x7f]*` between each letter of the scheme name:
```python
r'j[\s\x00-\x1f\x7f]*a[\s\x00-\x1f\x7f]*v[\s\x00-\x1f\x7f]*a[\s\x00-\x1f\x7f]*s[\s\x00-\x1f\x7f]*c[\s\x00-\x1f\x7f]*r[\s\x00-\x1f\x7f]*i[\s\x00-\x1f\x7f]*p[\s\x00-\x1f\x7f]*t[\s\x00-\x1f\x7f]*:'
```

### Case variation
Use `re.IGNORECASE` for all scheme detection patterns.

## Preservation Strategy

The key principle: **remove only what is dangerous, keep everything else intact**.

### What to preserve:
- All text content
- Safe HTML structure (div, p, span, h1-h6, etc.)
- Safe attributes (class, id, style without expressions, title, etc.)
- SVG graphics (circle, rect, path, text, polygon, etc.)
- SMIL animations (animate, animateColor, animateMotion, animateTransform) — they are safe visual animations; only their event handler attributes and dangerous URL attributes are removed
- MathML equations (mrow, mfrac, mi, mn, mo, etc.)
- Forms with safe actions
- Links with safe hrefs
- Images with safe src
- Tables, lists, semantic HTML
- HTML entities in text and attributes
- DOCTYPE declaration
- Comments (except IE conditional comments)
- Safe `<meta>` tags (charset, safe refresh)
- Safe `<link>` tags (stylesheets)

### What to remove:
- Only the dangerous tags, attributes, or URL values
- The surrounding safe content stays untouched

## Implementation Template

```python
#!/usr/bin/env python3
import sys, re, os, html as html_module
from bs4 import BeautifulSoup, Comment

# 1. Define dangerous tag sets
DANGEROUS_TAGS = frozenset(['script', 'iframe', 'object', 'embed', 'applet', 'base'])
DANGEROUS_SVG_TAGS = frozenset(['set', 'foreignobject', 'foreignobjectdata'])
DANGEROUS_MATHML_TAGS = frozenset(['annotation-xml'])
# Note: animate, animateColor, animateMotion, animateTransform are NOT removed.
# They are safe visual animations; only their attributes (event handlers, dangerous URLs) are cleaned in Phase 5.

# 2. Define URL attribute sets
URL_ATTRIBUTES = frozenset(['href', 'src', 'action', 'formaction', 'data', 'poster',
    'dynsrc', 'lowsrc', 'background', 'codebase', 'classid', 'usemap', 'longdesc',
    'ping', 'cite', 'manifest', 'xlink:href', 'content'])

# 3. Build obfuscation-tolerant patterns
_OBF = r'[\s\x00-\x1f\x7f]*'
_JS = r'j{0}a{0}v{0}a{0}s{0}c{0}r{0}i{0}p{0}t'.format(_OBF)
JS_URL_RE = re.compile(r'^\s*' + _JS + _OBF + r':', re.IGNORECASE)
# ... similar for vbscript, data:text/html, data:image/svg, etc.

# 4. Normalize URLs (decode entities iteratively)
def normalize_url(val):
    for _ in range(3):
        decoded = html_module.unescape(val)
        if decoded == val: break
        val = decoded
    return val

# 5. Check if URL is dangerous
def is_dangerous_url(val):
    if not isinstance(val, str): return False
    norm = normalize_url(val).strip()
    return bool(JS_URL_RE.match(norm) or VB_URL_RE.match(norm)
                or DATA_HTML_RE.match(norm) or DATA_SVG_RE.match(norm))

# 6. Main sanitization pipeline
def sanitize(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove IE conditional comments
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        if re.search(r'\[if\s', str(c), re.I): c.extract()
    
    # Remove dangerous tags
    for tag_name in DANGEROUS_TAGS | DANGEROUS_SVG_TAGS | DANGEROUS_MATHML_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    
    # Sanitize <style> element content (CSS-based XSS)
    # Use .get_text() for robustness (handles multiple children)
    for style_tag in soup.find_all('style'):
        css_text = style_tag.get_text()
        if css_text and has_dangerous_css(css_text):
            style_tag.decompose()
    
    # Remove dangerous meta refresh
    for meta in soup.find_all('meta'):
        # check http-equiv="refresh" with dangerous url in content
        ...
    
    # Clean attributes
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith('on'):
                del tag[attr]
            elif attr.lower() in URL_ATTRIBUTES:
                if is_dangerous_url(tag.attrs[attr]):
                    del tag[attr]
            elif attr.lower() == 'style':
                if dangerous_css(tag.attrs[attr]):
                    del tag[attr]
    
    result = str(soup)
    # Regex fallback for script tags
    result = re.sub(r'<\s*/?\s*script\b[^>]*>', '', result, flags=re.IGNORECASE)
    return result

# 7. Main: read file, sanitize, write back
if __name__ == '__main__':
    path = sys.argv[1]
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(sanitize(content))
```

## Key Gotchas

1. **BS4 lowercases tag names** with `html.parser` — search for `animatecolor` not `animateColor`
2. **BS4 decodes entities** in attribute values — `&#106;avascript:` becomes `javascript:` automatically
3. **Double encoding** requires iterative `html.unescape()` calls
4. **`<meta http-equiv="refresh">`** content attribute contains `url=...` — need to extract and check the URL separately
5. **srcset** contains multiple URLs — check each one individually
6. **SVG `<use>` and `<image>`** use `xlink:href` — must check this attribute
7. **`<foreignObject>`** can embed full HTML with scripts — remove entirely
8. **CSS `expression()`** in style attributes can execute JavaScript — remove the entire style attribute
9. **Null bytes** in tag names (`<scr\x00ipt>`) are not parsed as tags by html.parser — they're safe as text
10. **Attribute order** may change after BS4 serialization — this is acceptable
11. **`<style>` element content** can contain executable CSS (`expression()`, `behavior:`, `javascript:` URLs) — must check text content, not just `style` attributes
12. **`<annotation-xml>`** in MathML can embed foreign HTML/SVG that browsers execute — remove entirely
13. **SVG `<style>` elements** are also executable — the same CSS sanitization applies to `<style>` inside `<svg>`
14. **SMIL `<animate>` elements are NOT inherently dangerous** — they are visual animations. Only remove their event handler attributes (`onbegin`, `onend`, etc.) and dangerous URL attributes (`xlink:href` with `javascript:`). Do NOT remove the `<animate>` tag itself.
15. **`<set>` IS inherently dangerous** because it can dynamically set any attribute (including `xlink:href`) to a `javascript:` URL. Remove `<set>` entirely.
16. **Use `.get_text()` not `.string`** when extracting CSS from `<style>` elements. BeautifulSoup's `.string` returns `None` when an element has multiple children (e.g., comment + text nodes), which could allow dangerous CSS to evade detection. `.get_text()` concatenates all descendant text regardless of child structure.

## Dependencies

- Python 3 with `beautifulsoup4` (bs4) installed
- Standard library: `re`, `os`, `sys`, `html`
