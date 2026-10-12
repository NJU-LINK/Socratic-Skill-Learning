---
name: filter-js-from-html
description: Remove executable JavaScript behavior from HTML files while preserving legitimate document structure, SVG graphics, MathML equations, forms, and other safe content. Handles HTML, SVG, MathML, and namespace-aware markup with browser-matching parsing.
---

# Filter JavaScript from HTML

## Task Family Definition

This skill addresses the family of HTML sanitization tasks defined by four variation dimensions:

1. **Executable HTML vectors**: Which HTML constructs can cause script execution (script tags, inline event handlers, javascript: URLs, data URLs with executable MIME types, active containers like iframe/object/embed, SVG/MathML execution vectors, SMIL animations that mutate attributes, form-related targets, refresh/navigation paths)

2. **Preservation fidelity**: How much benign HTML structure must remain unchanged (common document structure, tables, forms, semantic HTML, entities, images, formatting, dense attribute sets, mixed safe/unsafe attributes, nested content where only small fragments are unsafe)

3. **HTML parsing irregularity**: How regular or adversarial the input syntax is (malformed tags, unusual spacing, case variation, entity-encoded content, tab characters, embedded templates, broken nesting, partially encoded payloads, browser-tolerated invalid markup)

4. **Payload obfuscation**: How directly dangerous behavior is expressed (plain script tags, mixed-case tags, HTML entities, null-byte-like strings, base64-encoded HTML, percent-encoding, layered encodings, fragmented payloads, executable content in long attributes or CSS-like constructs)

## Core Architecture

### Parse with html5lib, Never the Default Parser

Always use `BeautifulSoup(content, "html5lib")` rather than the default `html.parser`. html5lib replicates browser parsing behavior, including how it normalizes malformed markup. This is critical because the filter must match what the browser would actually execute — if the parser disagrees with the browser, an attacker can slip payloads through the gap.

### Multi-Phase Sanitization

The sanitization proceeds in distinct phases:

0. **Handle noscript content** (html5lib parses noscript as raw text when scripting is disabled, so dangerous patterns must be removed via regex)
1. **Remove inherently dangerous elements** (script, iframe, frame, frameset, object, embed, applet, base, foreignObject)
1b. **Remove `<style>` elements** entirely (they can contain arbitrary dangerous CSS)
2. **Handle special cases** (meta http-equiv="refresh" with dangerous URLs, link rel="import" or dangerous hrefs)
3. **Sanitize SMIL animation elements** (animate, set, animatemotion, animatetransform) that can mutate dangerous attributes
4. **Sanitize attributes on all remaining elements** (remove event handlers, analyze style attributes for dangerous CSS, remove dangerous URL schemes)
5. **Remove HTML comments** (IE conditional comments can execute code)
6. **Serialize and handle fragment vs full document**

## Dangerous Element Set

Remove these elements entirely (decompose them):

- **script**: Direct JavaScript execution (in HTML, SVG, and MathML namespaces)
- **iframe, frame, frameset**: Can load JavaScript via src attribute
- **object, embed, applet**: Can execute plugins or load external content
- **base**: Can rebase all relative URLs to javascript: (subtle attack: `<base href="javascript:alert(1)//">` makes all relative links execute)
- **foreignObject**: Embeds HTML inside SVG with different parsing context; almost exclusively an attack vector

**`<style>` elements vs `style` attributes**: `<style>` elements should be removed entirely (they contain arbitrary CSS blocks). But `style` **attributes** on elements should be analyzed — only remove them if they contain dangerous CSS patterns. Safe CSS like `color: red; font-weight: bold` must be preserved.

**Do NOT unconditionally remove**: meta, link, form, a, img — these have legitimate uses. Instead, sanitize their attributes or conditionally remove based on dangerous content.

### Special Element Handling

**meta tags**: Only remove `<meta http-equiv="refresh">` when its content attribute contains a dangerous URL. Keep charset, viewport, description, and other safe meta tags.

**link tags**: Remove `<link rel="import">` (HTML imports can execute). Sanitize href attribute — remove the link if href uses javascript:, vbscript:, or dangerous data: schemes. Keep safe stylesheets, icons, fonts.

**form tags**: Keep the form element. Sanitize action and formaction attributes to block dangerous URL schemes. Preserve method, enctype, and other safe attributes.

## Attribute Sanitization

### Event Handlers

Remove ALL attributes starting with `on` (case-insensitive): onclick, ONLOAD, OnError, onmouseover, etc. This covers all DOM event handlers.

### Style Attributes (Content Analysis Required)

**Do NOT remove all `style` attributes unconditionally.** Instead, analyze the CSS content and only remove the attribute if it contains dangerous patterns:

**Dangerous CSS patterns** (remove the style attribute if found):
- `expression(...)` — IE CSS expression, executes JavaScript
- `-moz-binding:` — Firefox XBL binding, can load external resources
- `behavior:` — IE behavior property, can load HTC files
- `url(javascript:...)` — CSS url() with javascript: scheme
- `url(vbscript:...)` — CSS url() with vbscript: scheme
- `url(data:...)` — CSS url() with data: scheme (potentially dangerous)

**Safe CSS** (preserve the style attribute):
- `color: red; font-weight: bold` — simple property values
- `background-color: #fff` — safe property values
- `margin: 10px; padding: 5px` — layout properties
- Any CSS that doesn't match the dangerous patterns above

```python
DANGEROUS_CSS_PATTERNS = [
    re.compile(r'expression\s*\(', re.IGNORECASE),
    re.compile(r'-moz-binding\s*:', re.IGNORECASE),
    re.compile(r'behavior\s*:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*javascript:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*vbscript:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*data\s*:', re.IGNORECASE),
]

def is_dangerous_css(css_text):
    if not css_text or not isinstance(css_text, str):
        return False
    for pattern in DANGEROUS_CSS_PATTERNS:
        if pattern.search(css_text):
            return True
    return False

# In attribute sanitization:
if attr_lower == 'style':
    style_val = tag[attr]
    if isinstance(style_val, list):
        style_val = ' '.join(style_val)
    if is_dangerous_css(style_val):
        attrs_to_remove.append(attr)
    # If CSS is safe, keep the style attribute
    continue
```

### URL Attributes

For attributes that accept URLs (href, src, action, formaction, data, poster, background, dynsrc, lowsrc, xlink:href, formtarget), check for dangerous schemes:

**Always block**:
- `javascript:` (any case, with whitespace/control chars)
- `vbscript:` (any case)

**Conditionally block data: URLs**:
- Use allowlist approach: only allow known-safe MIME types
- Allow `data:image/png`, `data:image/jpeg`, `data:image/gif`, `data:image/webp`, `data:image/bmp`, `data:image/ico`, `data:font/*`, `data:application/font`
- Block everything else including bare `data:` with no MIME type, `data:text/html`, `data:image/svg+xml`, `data:application/xml`, `data:application/xhtml+xml`

**Handle obfuscation**:
- Strip whitespace, control characters (0x00-0x1F, 0x7F), AND U+FFFD (replacement character) before checking
- U+FFFD is critical: HTML parsers convert null bytes (0x00) to U+FFFD, and browsers may strip it during URL resolution. Without stripping U+FFFD, `java\x00script:` becomes `java\ufffdscript:` which bypasses scheme detection
- Percent-decode before checking (handles `%6A%61%76%61%73%63%72%69%70%74%3A` → `javascript:`)
- Check both the raw value and the decoded value

## SVG and MathML Execution Vectors

SVG and MathML can contain executable content beyond just `<script>` tags:

### Direct Execution
- `<svg onload="...">`, `<svg><script>...</script></svg>`
- `<math><mtext><script>...</script></mtext></math>`

### SMIL Animation Attacks
SMIL elements can mutate attributes to create execution vectors:
- `<animate attributeName="onmouseover" to="alert(1)">` — sets event handler
- `<set attributeName="href" to="javascript:alert(1)">` — mutates link href
- `<animate attributeName="onclick" to="alert(1)">` — sets event handler

**Detection**: Check the `attributeName` attribute (case-insensitive lookup) against dangerous targets: `on*`, `href`, `src`, `xlink:href`, `action`, `formaction`. Also check `to` and `from` values for dangerous URLs.

### Safe SMIL Preservation
SMIL animations targeting safe attributes (width, height, x, y, cx, cy, r, fill, opacity, etc.) should be preserved. Only remove SMIL elements that target dangerous attributes or use dangerous URL values.

### foreignObject
`<foreignObject>` embeds HTML inside SVG with a different parsing context. Sanitization may miss vectors that only apply in the SVG foreign content context. Remove `<foreignObject>` entirely — it's almost exclusively an attack vector and rarely needed for legitimate SVG graphics.

## HTML Parsing Irregularity

### Noscript Parsing Trap

html5lib's BeautifulSoup integration has scripting disabled by default. This means `<noscript>` content is parsed as **raw text**, not as HTML elements. Consider:

```html
<noscript><script>alert(1)</script></noscript>
```

With scripting disabled, html5lib parses the `<script>alert(1)</script>` as a NavigableString (text node), NOT as a Tag element. So `soup.find_all('script')` will NOT find it. Your filter will pass it through unchanged.

**Fix**: Add explicit `<noscript>` handling before the main sanitization phases:

```python
from bs4 import NavigableString

def sanitize_noscript_content(text):
    """Remove dangerous patterns from noscript raw text content."""
    # Remove script tags
    text = re.sub(r'<\s*script\b[^>]*>.*?<\s*/\s*script\s*>', '', text, flags=re.IGNORECASE | re.DOTALL)
    # Remove event handlers
    text = re.sub(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+on\w+\s*=\s*\S+', '', text, flags=re.IGNORECASE)
    # Remove dangerous URL attributes
    text = re.sub(r'\s+(href|src|action)\s*=\s*["\']?\s*(javascript|vbscript|data):[^"\'>\s]*["\']?', '', text, flags=re.IGNORECASE)
    return text

# Pre-phase: Handle <noscript> content
for noscript in soup.find_all('noscript'):
    for child in list(noscript.children):
        if isinstance(child, NavigableString):
            text = str(child)
            cleaned_text = sanitize_noscript_content(text)
            if cleaned_text != text:
                child.replace_with(NavigableString(cleaned_text))
```

This is the kind of edge case the spec's `html_parsing_irregularity` axis describes — "payloads whose danger only becomes apparent after normalization or parsing."

### Case Variation
HTML is case-insensitive for tag names and attribute names. Use case-insensitive matching:
- Tag names: `soup.find_all('script')` matches `<SCRIPT>`, `<Script>`, etc.
- Attribute names: Use case-insensitive lookup for attributeName, http-equiv, etc.

### Whitespace and Control Characters
Browsers strip whitespace and control characters (0x00-0x1F, 0x7F) from URL schemes before processing. Additionally, HTML parsers convert null bytes (0x00) to U+FFFD (replacement character), which browsers may also strip during URL resolution. Strip all of these before checking:
```python
cleaned = re.sub(r'[\s\x00-\x1f\x7f\ufffd]', '', value)
```
Without stripping U+FFFD, an attacker can use `java\x00script:` which the parser converts to `java\ufffdscript:` — this bypasses scheme detection unless U+FFFD is also stripped.

### Entity Encoding
HTML entities in attribute values are decoded by the parser. BeautifulSoup handles this automatically. However, percent-encoding in URLs is NOT decoded by the HTML parser — it's decoded later during URL resolution. You must explicitly percent-decode before checking.

### Malformed Markup
html5lib handles malformed markup by replicating browser parsing behavior. This includes:
- Unclosed tags
- Misnested tags
- Missing quotes around attributes
- Duplicate attributes (browser uses first value)

Trust html5lib's parsing — it matches what the browser will actually see.

## Preservation Fidelity

### Minimize Changes
Only remove or modify what is dangerous. Preserve:
- Document structure (html, head, body, title, meta charset/viewport)
- Semantic HTML (header, nav, main, article, section, footer)
- Formatting (strong, em, b, i, u, span, div, p, br, hr)
- Tables (table, thead, tbody, tfoot, tr, th, td)
- Forms (form with safe action, input, button, select, textarea, label)
- Links (a with safe href)
- Images (img with safe src, including data:image/* URLs)
- SVG graphics (svg, circle, rect, path, text, g, defs, use with safe attributes)
- MathML equations (math, mrow, mi, mn, mo, mtext with safe content)
- Safe SMIL animations (animate targeting safe attributes)
- Safe style attributes (style="color: red; font-weight: bold" — CSS without dangerous patterns)

### Attribute Preservation
When sanitizing an element, only remove dangerous attributes. Keep all safe attributes:
- Class, id, title, alt, role, aria-*
- Dimensions (width, height, cx, cy, r, x, y)
- Styling (fill, stroke, color, and safe style attributes with non-dangerous CSS)
- Form attributes (method, enctype, name, value, placeholder)
- Link attributes (target, rel — but sanitize href)

### Fragment vs Full Document

Detect whether the input is a fragment (no `<html>` tag) or a full document. html5lib wraps fragments in `<html><head></head><body>...</body></html>`. For fragments, extract just the body content after sanitization to avoid adding unwanted document structure:

```python
is_fragment = not re.search(r'<html[\s>]', content, re.IGNORECASE)
soup = BeautifulSoup(content, "html5lib")
# ... sanitize ...
if is_fragment:
    body = soup.find('body')
    if body:
        result = body.decode_contents()
```

## Implementation Pattern

```python
from bs4 import BeautifulSoup, Comment, NavigableString
import re, sys, urllib.parse

DANGEROUS_TAGS = frozenset({'script', 'iframe', 'frame', 'frameset', 
                             'object', 'embed', 'applet', 'base',
                             'foreignobject'})

DANGEROUS_CSS_PATTERNS = [
    re.compile(r'expression\s*\(', re.IGNORECASE),
    re.compile(r'-moz-binding\s*:', re.IGNORECASE),
    re.compile(r'behavior\s*:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*javascript:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*vbscript:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*data\s*:', re.IGNORECASE),
]

def is_dangerous_css(css_text):
    if not css_text or not isinstance(css_text, str):
        return False
    for pattern in DANGEROUS_CSS_PATTERNS:
        if pattern.search(css_text):
            return True
    return False

URL_ATTRS_LOWER = frozenset({'href', 'src', 'action', 'formaction', 'data', 
                              'poster', 'background', 'dynsrc', 'lowsrc', 
                              'xlink:href', 'formtarget'})

DANGEROUS_SCHEME_RE = re.compile(
    r'^[\s\x00-\x1f\x7f\ufffd]*(javascript|vbscript)\s*:', re.IGNORECASE)

BARE_DATA_RE = re.compile(
    r'^[\s\x00-\x1f\x7f\ufffd]*data\s*:', re.IGNORECASE)

SAFE_DATA_RE = re.compile(
    r'^[\s\x00-\x1f\x7f\ufffd]*data\s*:\s*(image/(png|jpeg|jpg|gif|webp|bmp|ico)|'
    r'font/|application/font)', re.IGNORECASE)

SMIL_DANGEROUS_ATTRS_RE = re.compile(
    r'^(on\w+|href|src|xlink:href|action|formaction)$', re.IGNORECASE)

def is_dangerous_url(value):
    if not value or not isinstance(value, str):
        return False
    # Strip whitespace, control chars, and U+FFFD (replacement char from null bytes)
    cleaned = re.sub(r'[\s\x00-\x1f\x7f\ufffd]', '', value)
    if DANGEROUS_SCHEME_RE.match(cleaned):
        return True
    if BARE_DATA_RE.match(cleaned):
        if not SAFE_DATA_RE.match(cleaned):
            return True
    try:
        decoded = urllib.parse.unquote(cleaned)
        decoded = re.sub(r'[\s\x00-\x1f\x7f\ufffd]', '', decoded)
        if DANGEROUS_SCHEME_RE.match(decoded):
            return True
        if BARE_DATA_RE.match(decoded) and not SAFE_DATA_RE.match(decoded):
            return True
    except Exception:
        pass
    return False

def get_attr_case_insensitive(tag, attr_name_lower):
    if attr_name_lower in tag.attrs:
        return tag.attrs[attr_name_lower]
    for key, val in tag.attrs.items():
        if key.lower() == attr_name_lower:
            return val
    return None

def sanitize_noscript_content(text):
    """Remove dangerous patterns from noscript raw text content."""
    # Remove script tags
    text = re.sub(r'<\s*script\b[^>]*>.*?<\s*/\s*script\s*>', '', text,
                  flags=re.IGNORECASE | re.DOTALL)
    # Remove event handlers
    text = re.sub(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', '', text,
                  flags=re.IGNORECASE)
    text = re.sub(r'\s+on\w+\s*=\s*\S+', '', text, flags=re.IGNORECASE)
    # Remove dangerous URL attributes
    text = re.sub(r'\s+(href|src|action)\s*=\s*["\']?\s*'
                  r'(javascript|vbscript|data):[^"\'>\s]*["\']?', '', text,
                  flags=re.IGNORECASE)
    return text

def sanitize(content):
    is_fragment = not re.search(r'<html[\s>]', content, re.IGNORECASE)
    soup = BeautifulSoup(content, "html5lib")
    
    # Pre-phase: Handle noscript raw text content
    # html5lib (with scripting disabled) parses noscript content as raw text.
    for noscript in soup.find_all('noscript'):
        for child in list(noscript.children):
            if isinstance(child, NavigableString):
                text = str(child)
                cleaned_text = sanitize_noscript_content(text)
                if cleaned_text != text:
                    child.replace_with(NavigableString(cleaned_text))
    
    # Phase 1: Remove dangerous elements (case-insensitive for SVG)
    # html5lib preserves SVG element case (e.g., foreignObject), so we must
    # iterate all tags and compare lowercased names
    for tag in soup.find_all(True):
        if tag.name and tag.name.lower() in DANGEROUS_TAGS:
            tag.decompose()
    
    # Phase 1b: Remove <style> elements entirely
    for style_tag in soup.find_all('style'):
        style_tag.decompose()
    
    # Phase 1.5: Handle meta refresh and link tags
    for meta in soup.find_all('meta'):
        http_equiv = meta.get('http-equiv', '')
        if isinstance(http_equiv, list):
            http_equiv = ' '.join(http_equiv)
        if http_equiv.lower().strip() == 'refresh':
            content_attr = meta.get('content', '')
            if isinstance(content_attr, list):
                content_attr = ' '.join(content_attr)
            if is_dangerous_url(content_attr) or 'javascript:' in content_attr.lower():
                meta.decompose()
    
    for link in soup.find_all('link'):
        rel = link.get('rel', [])
        if isinstance(rel, str):
            rel = [rel]
        if 'import' in [r.lower() for r in rel]:
            link.decompose()
            continue
        href = link.get('href', '')
        if isinstance(href, list):
            href = ' '.join(href)
        if is_dangerous_url(href):
            link.decompose()
    
    # Phase 2: Handle SMIL animations
    for smil_tag in soup.find_all(['animate', 'set', 'animatemotion', 'animatetransform']):
        attr_name = get_attr_case_insensitive(smil_tag, 'attributename') or ''
        if isinstance(attr_name, list):
            attr_name = ' '.join(attr_name)
        if SMIL_DANGEROUS_ATTRS_RE.match(attr_name.strip()):
            smil_tag.decompose()
        else:
            to_val = get_attr_case_insensitive(smil_tag, 'to') or ''
            from_val = get_attr_case_insensitive(smil_tag, 'from') or ''
            if isinstance(to_val, list):
                to_val = ' '.join(to_val)
            if isinstance(from_val, list):
                from_val = ' '.join(from_val)
            if is_dangerous_url(to_val) or is_dangerous_url(from_val):
                smil_tag.decompose()
    
    # Phase 3: Sanitize attributes
    for tag in soup.find_all(True):
        attrs_to_remove = []
        for attr in list(tag.attrs):
            attr_lower = attr.lower()
            if attr_lower.startswith('on'):
                attrs_to_remove.append(attr)
            elif attr_lower == 'style':
                # Analyze CSS content — only remove if dangerous
                style_val = tag[attr]
                if isinstance(style_val, list):
                    style_val = ' '.join(style_val)
                if is_dangerous_css(style_val):
                    attrs_to_remove.append(attr)
                # Safe CSS is preserved
            elif attr_lower in URL_ATTRS_LOWER:
                val = tag[attr]
                if isinstance(val, list):
                    val = ' '.join(val)
                if is_dangerous_url(val):
                    attrs_to_remove.append(attr)
        for attr in attrs_to_remove:
            del tag[attr]
    
    # Phase 4: Remove comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
    
    # Serialize
    result = str(soup)
    if is_fragment:
        body = soup.find('body')
        if body:
            result = body.decode_contents()
    
    return result
```

## Testing Approach

Test across all four variation dimensions:

**Executable vectors**: script tags (HTML/SVG/MathML), event handlers (onclick, onerror, onload, onmouseover), javascript: URLs (plain, mixed case, with whitespace), vbscript: URLs, data: URLs (text/html, image/svg+xml), iframe/object/embed, base tag, meta refresh, link import, SMIL animations targeting dangerous attributes

**Preservation**: Document structure, forms with safe actions, links with safe hrefs, images with safe src (including data:image/*), SVG graphics with safe animations, MathML equations, tables, semantic HTML, mixed safe/unsafe attributes on same element

**Parsing irregularity**: Mixed case tags and attributes, unusual whitespace, entity-encoded content, malformed markup, missing quotes, broken nesting

**Obfuscation**: Percent-encoded javascript: URLs, whitespace/control chars in schemes, base64-encoded HTML in data: URLs, layered encodings, fragmented payloads

## Key Insights

1. **Parse like a browser**: Use html5lib to match browser parsing behavior. If your parser disagrees with the browser, attackers can exploit the gap.

2. **SVG elements preserve case**: html5lib preserves the original case of SVG elements (e.g., `foreignObject` not `foreignobject`). When checking for dangerous tags, use case-insensitive comparison by iterating all tags and comparing `tag.name.lower()` against your dangerous tags set.

2. **Prefer attribute surgery over element removal**: Forms, links, images, and meta tags have legitimate uses. Only remove them if their attributes are dangerous.

3. **Handle encoding at the right layer**: HTML entities are decoded by the parser. Percent-encoding in URLs is NOT decoded by the parser — you must explicitly decode before checking.

4. **SMIL is a subtle vector**: Animate/set elements can mutate attributes to create execution paths. Check both the target attribute name and the values.

5. **data: URLs require allowlist approach**: Instead of listing dangerous MIME types, allow only known-safe types (image/png, image/jpeg, font/*) and block everything else including bare `data:` with no MIME type.

6. **Fragment detection matters**: html5lib wraps fragments in document structure. Detect fragments and extract body content to preserve the original structure.

7. **Test with real payloads**: The spec's variation dimensions describe real attack vectors. Test each one explicitly to ensure coverage.

8. **foreignObject is dangerous**: Remove it entirely rather than trying to sanitize its contents, as the HTML parsing context inside SVG is different and may bypass sanitization.

9. **Noscript requires regex sanitization**: html5lib parses noscript content as raw text (not HTML) when scripting is disabled. Use regex to strip dangerous patterns from noscript text nodes before the tag-based sanitization phases.

10. **Style attributes require content analysis, not blanket removal**: `<style>` elements should be removed entirely (arbitrary CSS blocks). But `style` attributes on elements should be analyzed — only remove if they contain dangerous CSS patterns (expression(), -moz-binding, behavior, url(javascript:...)). Safe CSS like `color: red; font-weight: bold` must be preserved. The test suite explicitly checks for this distinction.

11. **Null bytes become U+FFFD — strip them too**: HTML parsers convert null bytes (0x00) to U+FFFD (replacement character). Browsers may strip U+FFFD during URL resolution, so `java\x00script:` becomes `javascript:` in the browser. Your filter must strip U+FFFD along with other control characters when checking URL schemes, otherwise null-byte-obfuscated payloads bypass detection.
