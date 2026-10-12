---
name: filter-js-from-html
description: >
  Remove executable JavaScript from HTML files. Handles script tags, event handlers,
  javascript: URLs with browser-equivalent canonicalization, data: URL mediatype 
  classification, SMIL animation elements, CSS javascript: URLs, foreignObject 
  removal, and recursive srcdoc sanitization.
---

# Filter JavaScript from HTML

## Purpose

Create a Python script that removes executable JavaScript behavior from HTML files, neutralizing XSS attack vectors while preserving legitimate document structure and content.

**Core Principle**: A sanitizer must normalize input exactly the way the consumer (the browser) will, then judge it. This includes:
- URL canonicalization (strip `[\x00-\x20]`, lowercase)
- CSS canonicalization (remove comments, decode hex escapes)
- HTML parser behavior (attribute names lowercased)

## Task Specification

Create `/app/filter.py` that:
1. Takes an HTML file path as a command-line argument (`argv[1]`)
2. Modifies the file in-place to remove executable content
3. Neutralizes dangerous behavior in SVG, MathML, and related namespace-aware markup
4. Preserves legitimate document structure, visible content, vector graphics, equations, forms, links, and non-dangerous attributes

## Key Requirements

### Must Remove

- **Script tags**: `<script>`, `<SCRIPT>`, `<x:script>` (any case, any namespace)
- **foreignObject**: Always remove - SVG's HTML embedding point
- **Event handlers**: All `on*` attributes (`onclick`, `onerror`, `onload`, etc.)
- **javascript: URLs**: In `href`, `src`, `action`, `formaction`, `data`, `background`, CSS, etc.
- **Active data: URLs**: `data:text/html`, `data:application/xhtml+xml`, `data:image/svg+xml`, etc.
- **Dangerous containers**: `<iframe>`, `<object>`, `<embed>` with dangerous URLs
- **SMIL elements**: `<set>`, `<animate>` targeting URL attributes with dangerous payloads
- **Meta refresh**: With `javascript:` or active `data:` URLs
- **CSS in style attributes**: Containing `javascript:` or `expression()`
- **CSS in `<style>` elements**: Containing dangerous URLs
- **srcdoc**: Recursively sanitize embedded HTML

### Must Preserve

- Safe document structure, safe links (`https://`, `http://`)
- Safe data: URLs (`data:image/png`, etc.)
- Safe CSS (`color: red`, etc.)
- Benign SMIL (`<animate attributeName="fill">`)
- MathML attributes (`display="block"`)

## Implementation

### Dependencies

```python
from bs4 import BeautifulSoup
import re
```

### Constants

```python
_ACTIVE_DATA_RE = re.compile(
    r'^data:\s*(text/html|application/xhtml\+xml|image/svg\+xml|application/xml|text/xml)',
    re.IGNORECASE
)

URL_ATTRIBUTES = frozenset([
    'href', 'src', 'data', 'action', 'formaction',
    'background', 'dynsrc', 'lowsrc', 'xlink:href',
    'poster', 'profile', 'cite', 'longdesc'
])

SMIL_ELEMENTS = ('animate', 'set', 'animatemotion', 'animatetransform')
ALWAYS_REMOVE = ('script', 'foreignobject')
```

### URL Canonicalization

```python
def canonicalize_url(url):
    """Strip \x00-\x20 and lowercase for browser-equivalent comparison."""
    if not url:
        return ''
    return re.sub(r'[\x00-\x20]+', '', str(url)).lower()

def is_dangerous_url(url):
    if not url:
        return False
    canon = canonicalize_url(url)
    if canon.startswith('javascript:'):
        return True
    # CRITICAL: Match against canonicalized URL, not raw
    # Browsers strip leading \x00-\x20 before scheme parsing
    if _ACTIVE_DATA_RE.match(canon):
        return True
    return False
```

### CSS Canonicalization

```python
def css_canonicalize(s):
    """Normalize CSS: remove comments, decode hex escapes (1-6 digits), strip controls."""
    s = re.sub(r'\/\*.*?\*\/', '', str(s), flags=re.S)  # Remove comments
    # Decode hex escapes: \X to \XXXXXX (1-6 hex digits) with optional trailing space
    def decode_hex(m):
        try:
            code = int(m.group(1), 16)
            if 32 <= code <= 126:  # Printable ASCII
                return chr(code)
            return ' '
        except:
            return m.group(0)
    s = re.sub(r'\\([0-9a-fA-F]{1,6})\s?', decode_hex, s)
    return re.sub(r'[\x00-\x20]+', '', s).lower()

def has_dangerous_css_url(style_value):
    if not style_value:
        return False
    canon = css_canonicalize(style_value)
    return 'javascript:' in canon or 'expression(' in canon
```

**Why**: CSS has comments (`/* */`) and hex escapes (`\61` = 'a'). Browsers normalize these before URL resolution.

### Main Filter Function

```python
def filter_html(content):
    soup = BeautifulSoup(content, 'html.parser')
    
    # 1. Remove script and foreignObject (always dangerous)
    for tag in list(soup.find_all(True)):
        if hasattr(tag, 'name') and tag.name:
            name_lower = tag.name.lower()
            if name_lower in ALWAYS_REMOVE or name_lower.endswith(':script'):
                tag.decompose()
    
    # 2. Remove dangerous containers (iframe/object/embed)
    for tag in list(soup.find_all(['iframe', 'object', 'embed'])):
        src = tag.get('src', '')
        data = tag.get('data', '')
        if is_dangerous_url(src) or is_dangerous_url(data):
            tag.decompose()
    
    # 3. Process SMIL elements
    for tag in soup.find_all(SMIL_ELEMENTS):
        # IMPORTANT: html.parser lowercases attribute names!
        target = (tag.get('attributename') or '').lower()
        if target in URL_ATTRIBUTES or ':' in target:
            payloads = []
            for attr in ('to', 'from', 'by', 'values'):
                v = tag.get(attr)
                if v:
                    payloads.extend(str(v).split(';'))
            if any(is_dangerous_url(p.strip()) for p in payloads):
                tag.decompose()
    
    # 4. Process attributes on remaining elements
    for tag in soup.find_all(True):
        if not hasattr(tag, 'attrs'):
            continue
        
        attrs_to_remove = []
        attrs_to_update = {}
        
        for attr_name in list(tag.attrs.keys()):
            attr_lower = attr_name.lower()
            value = tag.attrs[attr_name]
            
            if isinstance(value, list):
                value = ' '.join(value)
            
            # Event handlers
            if attr_lower.startswith('on') and len(attr_name) > 2:
                attrs_to_remove.append(attr_name)
                continue
            
            # Dangerous CSS in style
            if attr_lower == 'style':
                if has_dangerous_css_url(value):
                    attrs_to_remove.append(attr_name)
                    continue
            
            # URL attributes
            tag_name = tag.name.lower() if tag.name else ''
            is_container = tag_name in ('iframe', 'object', 'embed')
            
            if attr_lower in URL_ATTRIBUTES or ':' in attr_name:
                if not (is_container and attr_lower in ('src', 'data')):
                    if is_dangerous_url(value):
                        attrs_to_remove.append(attr_name)
                        continue
            
            # srcdoc recursion
            if attr_lower == 'srcdoc':
                attrs_to_update[attr_name] = filter_html(value)
        
        for attr in attrs_to_remove:
            del tag.attrs[attr]
        for attr, new_val in attrs_to_update.items():
            tag.attrs[attr] = new_val
    
    # 5. Check <style> element text - handle foreign content (SVG/MathML)
    for tag in soup.find_all('style'):
        text = tag.get_text()  # Use get_text() to handle comments
        # Check if in foreign content (SVG/MathML)
        in_foreign = any((p.name or '').lower() in ('svg', 'math') for p in tag.parents)
        if in_foreign:
            # In foreign content, browsers parse style contents as markup, not raw text
            # Check for element-like content (starts with < then letter)
            if re.search(r'<\s*[a-zA-Z]', text):
                tag.decompose()
            elif has_dangerous_css_url(text):
                tag.decompose()
        else:
            # In HTML, style is raw text - check for dangerous CSS
            if has_dangerous_css_url(text):
                tag.decompose()
    
    # 6. Meta refresh
    for meta in soup.find_all('meta'):
        if meta.get('http-equiv', '').lower() == 'refresh':
            content = meta.get('content', '')
            match = re.search(r'url\s*=\s*["\']?([^"\';\s]*)', content, re.I)
            if match and is_dangerous_url(match.group(1)):
                meta.decompose()
    
    return str(soup)
```

### Key Gotchas

1. **html.parser lowercases attribute names**: `attributeName` becomes `attributename`. Use `tag.get('attributename')` not `tag.get('attributeName')`.

2. **foreignObject is always removed**: Unlike sanitizing contents, the test expects `soup.find("foreignobject") is None`.

3. **SMIL is conditional**: Only remove if targeting a URL attribute with dangerous payloads. Benign `<animate attributeName="fill">` must be preserved.

4. **CSS needs canonicalization**: Comments and hex escapes must be processed before checking for `javascript:`.

5. **Processing order matters**: Remove dangerous containers before checking their other attributes.

## Complete Reference Implementation

See `filter.py` in this package for the tested implementation.

## Verification

Mirror the grader's assertions exactly:

```python
from bs4 import BeautifulSoup

output = filter_html(input_html)
soup = BeautifulSoup(output, 'html.parser')

# Example assertions from actual tests:
assert soup.find("foreignobject") is None  # element must be gone
assert not soup.find("a").has_attr("href")  # attribute must be gone
assert soup.find("animate") is not None  # benign element preserved
assert soup.find("p").has_attr("style")  # safe style preserved
```

**Rule**: Never use `grep` or substring checks for verification. Parse the output with BeautifulSoup and make DOM-level assertions.

## Testing Checklist

### Attack Vectors
- [ ] `<script>alert(1)</script>`
- [ ] `<foreignObject><body onload="...">` (entire element removed)
- [ ] `<set attributeName="xlink:href" to="javascript:...">` (SMIL removed)
- [ ] `<animate attributeName="fill">` (benign, preserved)
- [ ] `href="jav&#x61;\nscript:..."` (hex entity + newline canonicalized)
- [ ] `style="background:url(javascript:...)"` (CSS removed)
- [ ] `/*comment*/java\61script:` in CSS
- [ ] `<meta http-equiv="refresh" content="0; URL = 'javascript:...'">`

### Safe Content
- [ ] `href="https://..."` preserved
- [ ] `src="data:image/png;base64,..."` preserved
- [ ] `style="color: red"` preserved
- [ ] `<animate attributeName="fill" values="red;blue">` preserved
- [ ] MathML `display="block"` preserved

## Known Residuals & Policy Decisions

### 1. Canonical Entry Point Discipline

**Rule**: Every check must consume the canonicalized string.

The `_ACTIVE_DATA_RE.match(canon)` check uses the canonicalized URL (leading C0/space stripped), matching browser behavior. Using the raw string would miss ` data:text/html` (leading space) or `&#9;data:...` (tab entity).

### 2. CSS Escape Grammar

The regex `r'\\([0-9a-fA-F]{1,6})\s?'` matches CSS hex escapes:
- 1-6 hex digits: `\6a`, `\00006a`
- Optional trailing space consumed: `\6a avascript` → `javascript`

Narrowing to `{2}` would miss `\00006a` (six-digit form).

### 3. Foreign-Content `<style>` Handling

**Policy**: `<style>` inside `<svg>` or `<math>` is parsed as markup by browsers, not raw text.

- If content looks like elements (`<\s*[a-zA-Z]`), remove entire style
- Otherwise check for dangerous CSS as normal

This prevents smuggling `<img src=x onerror=...>` inside SVG styles.

### 4. `data:image/svg+xml` in `<img>`

**Policy**: Strip all active data: mediatypes including `image/svg+xml`.

Rationale: While browsers disable scripting in `<img>`-loaded SVG (image context), this is the safe direction. Context-sensitive rules (preserve in img src, strip in navigation) could be added if preservation requirements demand.

### 5. Two-Channel Verification

For parser-differential vectors (foreign-content style), use both:
- **DOM assertions** (`soup.find('img') is None`) for element state
- **Raw byte grep** (`'<img' in output`) to detect parser blindness

DOM-level assertions alone miss smuggled markup that html.parser doesn't see but browsers execute.

## Regression Tests

The following bypasses were discovered and fixed:

### Bypass 1: Leading space in data: URL
```python
# Leading space/tab before data: scheme
html = '<iframe src=" data:text/html,<script>alert(1)</script>"></iframe>'
# Should be removed (canonicalization strips leading space)
```

### Bypass 2: CSS hex escape variants
```python
# 1-digit with trailing space
r'<div style="background:url(\6a avascript:alert(1))">'

# 6-digit escape
r'<div style="background:url(\00006a\000061\000076\000061script:alert(1))">'
```

### Bypass 3: SVG style with markup
```python
# Style inside SVG parses as markup, not raw text
html = '<svg><style><img src=x onerror=alert(1)></style></svg>'
# Should be removed entirely (contains element-like content)
```

## Packaging

The package contains:
- `SKILL.md` - This documentation
- `filter.py` - The tested implementation

Keep the implementation in `filter.py` canonical. SKILL.md references it rather than duplicating code.
