---
name: filter-js-from-html
description: Remove executable JavaScript behavior from HTML while preserving safe content structure, with special handling for SVG, MathML, encoding obfuscation, and namespace-aware markup
---

# Filter JavaScript from HTML

## Core Mechanism

Use a **single-pass sanitization approach** with BeautifulSoup and html5lib parser:

1. **Parse with html5lib**: Implements HTML5 parsing algorithm, handles SVG/MathML correctly
2. **Remove dangerous tags**: Decompose script, style, iframe, object, embed, applet (including content)
3. **Apply allowlist rules**: Walk all tags, validate against tag/attribute allowlists
4. **Special handling**: Validate SVG animation elements, MathML maction, dangerous URL schemes

**Never use regex or string manipulation** to parse/sanitize HTML. Browsers use complex parsing algorithms that no regex can faithfully replicate.

**Why BS4-only instead of bleach?** Bleach strips SVG elements even when in allowlist due to how it handles foreign content. BS4 with html5lib correctly parses and preserves SVG/MathML while allowing full control over sanitization rules.

## Implementation Pattern

```python
from bs4 import BeautifulSoup, Comment
import re

# 1. Parse with html5lib: BeautifulSoup(html, 'html5lib')
# 2. Pre-remove dangerous tags with decompose()
# 3. Remove comments to prevent mutation XSS
# 4. Walk all tags: check against SAFE_TAGS, validate attributes
# 5. Special handling for SVG animation, MathML maction
# 6. Serialize back (body content or full document)
```

## Complete Working Implementation Template

Below is a complete, tested implementation. Adapt as needed but preserve the critical logic:

```python
#!/usr/bin/env python3
import subprocess, sys, importlib

def ensure_dependencies():
    packages = ['beautifulsoup4', 'html5lib']
    for pkg in packages:
        try:
            if pkg == 'beautifulsoup4':
                import bs4
            elif pkg == 'html5lib':
                import html5lib
        except ImportError:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', pkg])
            importlib.invalidate_caches()
            for mod_name in list(sys.modules.keys()):
                if pkg.replace('-', '_') in mod_name:
                    del sys.modules[mod_name]

ensure_dependencies()

import re
from bs4 import BeautifulSoup, Comment

# CRITICAL: Safe data: URI prefixes (allow these, block all other data: URIs)
SAFE_DATA_PREFIXES = [
    'data:image/png', 'data:image/jpeg', 'data:image/jpg',
    'data:image/gif', 'data:image/webp', 'data:image/bmp',
    'data:audio/', 'data:video/',
]

def is_dangerous_url(value):
    """Check if URL contains dangerous scheme."""
    if not value or not isinstance(value, str):
        return False
    cleaned = re.sub(r'[\s\x00-\x1f\x7f]+', '', value)
    cleaned_lower = cleaned.lower()
    
    # Check javascript:/vbscript:
    if re.match(r'^(?:javascript|vbscript)\s*:', cleaned, re.IGNORECASE):
        return True
    if re.match(r'j\s*a\s*v\s*a\s*s\s*c\s*r\s*i\s*p\s*t\s*:', cleaned, re.IGNORECASE):
        return True
    
    # Check data: URIs - allow safe raster media, block everything else
    if cleaned_lower.startswith('data:'):
        for prefix in SAFE_DATA_PREFIXES:
            if cleaned_lower.startswith(prefix):
                return False
        return True  # Block all other data: URIs
    
    return False

# CRITICAL: Dangerous CSS patterns
DANGEROUS_CSS_PATTERNS = [
    re.compile(r'expression\s*\(', re.IGNORECASE),
    re.compile(r'behavior\s*:', re.IGNORECASE),
    re.compile(r'-moz-binding\s*:', re.IGNORECASE),
    re.compile(r'-ms-behavior\s*:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*javascript:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*vbscript:', re.IGNORECASE),
    re.compile(r'@import\s+["\']?\s*javascript:', re.IGNORECASE),
]

def is_safe_style(style_value):
    """Check if CSS style is safe."""
    if not style_value:
        return True
    for pattern in DANGEROUS_CSS_PATTERNS:
        if pattern.search(style_value):
            return False
    return True

def get_attr_case_insensitive(tag, attr_name):
    """Get attribute value with case-insensitive lookup."""
    attr_name_lower = attr_name.lower()
    for key in tag.attrs.keys():
        if key.lower() == attr_name_lower:
            return tag.attrs[key]
    return ''

def is_dangerous_svg_animation(tag):
    """Check if SVG animation has dangerous values."""
    tag_name = tag.name.lower()
    if tag_name not in ['animate', 'animatetransform', 'animatemotion', 'set']:
        return False
    
    # Check attributeName targeting event handlers
    attr_name_val = get_attr_case_insensitive(tag, 'attributename').lower()
    if attr_name_val.startswith('on'):
        return True
    
    # Check to, from, by, values for dangerous URIs or code
    for check_attr in ['to', 'from', 'by', 'values', 'href', 'xlink:href']:
        val = tag.get(check_attr, '')
        if is_dangerous_url(val) or re.search(r'(?:alert|eval|exec|function|document|window)\s*\(', val, re.IGNORECASE):
            return True
    
    return False

def sanitize_html(html_content):
    original_lower = html_content.strip().lower()
    is_full_document = original_lower.startswith('<!doctype') or '<html' in original_lower
    
    soup = BeautifulSoup(html_content, 'html5lib')
    
    # Step 1: Remove dangerous tags and content
    for tag_name in ['script', 'style', 'iframe', 'object', 'embed', 'applet']:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    
    # Step 2: Remove comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    
    # Step 3: CRITICAL - Remove ALL meta refresh tags (navigation vector)
    for meta in soup.find_all('meta'):
        http_equiv = meta.get('http-equiv', '').lower()
        if http_equiv == 'refresh':
            meta.decompose()
    
    # Step 4: Walk all tags
    for tag in soup.find_all(True):
        tag_name = tag.name.lower()
        
        # Check if tag is in SAFE_TAGS (define your allowlist)
        if tag_name not in SAFE_TAGS:
            if tag_name == 'maction':
                actiontype = get_attr_case_insensitive(tag, 'actiontype').lower()
                if actiontype != 'toggle':
                    tag.unwrap()
                    continue
            else:
                tag.unwrap()
                continue
        
        # CRITICAL: Check dangerous SVG animations BEFORE attribute filtering
        if is_dangerous_svg_animation(tag):
            tag.decompose()
            continue
        
        # Validate attributes
        attrs_to_remove = []
        for attr_name in list(tag.attrs.keys()):
            attr_name_lower = attr_name.lower()
            
            # Block event handlers
            if re.match(r'^on[a-z]+$', attr_name, re.IGNORECASE):
                attrs_to_remove.append(attr_name)
                continue
            
            val = tag.attrs[attr_name]
            if isinstance(val, list):
                val = ' '.join(val)
            
            # CRITICAL: Check style content BEFORE allowlist
            if attr_name_lower == 'style':
                if not is_safe_style(val):
                    attrs_to_remove.append(attr_name)
                    continue
            
            # Check for dangerous URLs
            if is_dangerous_url(val):
                attrs_to_remove.append(attr_name)
                continue
            
            # Check allowlist (define SAFE_ATTRIBUTES)
            allowed = False
            if tag_name in SAFE_ATTRIBUTES:
                if attr_name_lower in SAFE_ATTRIBUTES[tag_name]:
                    allowed = True
                elif attr_name_lower in SAFE_ATTRIBUTES['*']:
                    allowed = True
                elif attr_name_lower.startswith('data-'):
                    allowed = True
            else:
                if attr_name_lower in SAFE_ATTRIBUTES['*']:
                    allowed = True
                elif attr_name_lower.startswith('data-'):
                    allowed = True
            
            if not allowed:
                attrs_to_remove.append(attr_name)
        
        for attr_name in attrs_to_remove:
            del tag[attr_name]
    
    if is_full_document:
        return str(soup)
    else:
        body = soup.find('body')
        return body.decode_contents() if body else str(soup)

# SAFE_TAGS must include: 'use', 'meta', 'img', 'svg', 'animate', 'set', etc.
# SAFE_ATTRIBUTES must include 'style' in '*' wildcard, 'href' for 'a', 'src' for 'img', etc.

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        sys.exit(1)
    filepath = sys.argv[1]
    with open(filepath, 'r', encoding='utf-8') as f:
        html_content = f.read()
    sanitized = sanitize_html(html_content)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(sanitized)
```

**CRITICAL RULES:**
1. `use` tag MUST be in SAFE_TAGS - only strip dangerous `href`/`xlink:href` attributes
2. `meta` tag MUST be in SAFE_TAGS - remove ALL meta refresh tags (not just dangerous ones)
3. `style` MUST be in SAFE_ATTRIBUTES['*'] - validate content BEFORE allowlist check
4. data: URIs for safe raster images (png, jpeg, gif, webp, bmp) MUST be preserved

## Critical Design Decisions

### Allowlist vs. Blocklist

**Use allowlist-based approach** (specify what's safe, remove everything else):
- More robust than blocklist (which inevitably misses vectors)
- May over-sanitize but won't miss attack vectors
- For tags not in allowlist: unwrap (keep children) except for maction (special handling)
- For attributes not in allowlist: remove entirely
- Universal checks apply to ALL attributes (event handlers, dangerous URLs)

### Tag Allowlist Strategy

**Include in SAFE_TAGS:**
- Standard HTML structure (div, p, span, tables, forms, etc.)
- SVG elements (svg, g, path, circle, rect, text, animate, etc.)
- MathML elements (math, mi, mn, mo, mrow, mfrac, etc.)
- Media elements (img, audio, video, canvas)

**Exclude from SAFE_TAGS:**
- `script`, `iframe`, `object`, `embed`, `applet` - obvious execution vectors
- `style` - can contain executable CSS (expression(), url(), -moz-binding)
- `base` - can affect URL resolution and link behavior
- `noscript`, `template` - mutation XSS risk through re-parsing
- `foreignObject` - allows arbitrary HTML in SVG context
- `maction` - handle specially in post-processing

### Attribute Filtering

**Universal checks (apply to ALL attributes):**
1. Block event handlers: `^on[a-z]+$` pattern
2. Block dangerous URL schemes: `javascript:`, `vbscript:`, `data:`
3. Handle obfuscated schemes: whitespace/control chars between letters
4. **Validate attribute CONTENT before allowlist check** (critical for style, data-*, etc.)

**Tag-specific allowlists:**
- Define safe attributes per tag (href, src, alt, class, id, etc.)
- Wildcard attributes apply to all tags (aria-*, data-*, xmlns, etc.)
- Validate URL-bearing attributes for dangerous schemes

**Style attribute validation (CRITICAL):**
The `style` attribute must be in the allowlist to preserve safe CSS, BUT you must validate the CSS content BEFORE the allowlist check. Dangerous CSS patterns include:
- `expression()` - IE CSS expression (can execute JavaScript)
- `behavior:` - IE CSS property (can load external resources)
- `-moz-binding:` - Firefox XBL binding (can execute code)
- `-ms-behavior:` - IE behavior
- `url(javascript:)` or `url(vbscript:)` in any CSS property
- `@import` with dangerous URLs

```python
DANGEROUS_CSS_PATTERNS = [
    re.compile(r'expression\s*\(', re.IGNORECASE),
    re.compile(r'behavior\s*:', re.IGNORECASE),
    re.compile(r'-moz-binding\s*:', re.IGNORECASE),
    re.compile(r'-ms-behavior\s*:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*javascript:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*vbscript:', re.IGNORECASE),
    re.compile(r'@import\s+["\']?\s*javascript:', re.IGNORECASE),
]

def is_safe_style(style_value):
    for pattern in DANGEROUS_CSS_PATTERNS:
        if pattern.search(style_value):
            return False
    return True

# In attribute filtering loop:
if attr_name_lower == 'style':
    if not is_safe_style(val):
        attrs_to_remove.append(attr_name)
        continue
```

**Key principle:** Any attribute that could contain executable content (style, data-*, etc.) must have its content validated BEFORE the allowlist check, even if the attribute name itself is in the allowlist.

**URL-bearing attributes to validate:**
- `href`, `src`, `action`, `formaction`, `xlink:href`
- `poster`, `background`, `data`, `dynsrc`, `lowsrc`

### SVG/MathML Specific Handling

**SVG animation elements** (animate, animateTransform, set):
- Check `attributeName` - block if targeting event handlers (`on*`)
- Validate `to`, `from`, `by`, `values` for dangerous URIs or suspicious code patterns
- Remove elements with dangerous values entirely

**MathML maction:**
- Not in main allowlist - handle in post-processing
- Only allow safe actiontypes: `toggle`
- Unwrap (keep children) for unsafe actiontypes or dangerous URLs

**SVG use/image elements:**
- Validate `href` and `xlink:href` for dangerous URIs
- Block `data:` URIs that can embed executable HTML

### Encoding and Obfuscation

**Handle these encoding layers:**
1. HTML entities: `&#106;` → `j`, `&#x6A;` → `j`
2. Whitespace/control chars: `j a v a s c r i p t :`
3. Null bytes: `java\x00script:`
4. Mixed case: `JaVaScRiPt:`
5. Layered encoding: entities within entities

**Strategy:**
- Use html5lib parser (implements HTML5 parsing algorithm)
- Parser decodes entities before attribute filtering
- After decoding, normalize by removing whitespace/control chars
- Check normalized value against dangerous scheme patterns

### Preservation vs. Sanitization

**Preserve:**
- Document structure (html, head, body, title, meta)
- Visible content (text, images, tables, forms)
- SVG graphics (paths, shapes, gradients, text)
- MathML equations (all standard elements)
- Safe attributes (class, id, style without dangerous values, aria-*)
- Links with safe protocols (http, https, mailto, tel)

**Remove:**
- All executable JavaScript behavior
- Event handlers (onclick, onload, onerror, etc.)
- javascript:/vbscript:/data: URLs
- Script tag content (not just tags)
- Dangerous SVG animation targets
- Executable CSS (expression(), url(javascript:))

## Common Pitfalls

1. **Script text leaking**: `strip=True` removes tags but leaves text content. Pre-remove script tags with `decompose()` to remove content too.

2. **SVG foreignObject**: Allows arbitrary HTML in SVG. Must be excluded from allowlist.

3. **Base tag**: Even without dangerous href, `target` attribute affects all links. Remove entirely.

4. **Noscript/template**: Content can be reinterpreted during serialization/re-parsing (mutation XSS). Remove or escape.

5. **Style tags**: Can contain `@import`, `url()`, `expression()`, `-moz-binding`. Remove entirely.

6. **SVG animation values**: Check `to`/`from`/`by`/`values` not just for URLs but for suspicious code patterns like `alert(`, `eval(`.

7. **Attribute case sensitivity**: HTML attributes are case-insensitive, but html5lib has context-dependent rules:
   - **Standard HTML attributes** (`href`, `onclick`, `class`, etc.) → **always lowercased**
   - **SVG-specific attributes** (`attributeName`, `viewBox`, `preserveAspectRatio`, etc.) → **camelCase preserved** per SVG spec
   - **MathML attributes** → generally lowercased
   
   **Solution**: Use case-insensitive attribute lookups for SVG/MathML attributes:
   ```python
   def get_attr_case_insensitive(tag, attr_name):
       attr_name_lower = attr_name.lower()
       for key in tag.attrs.keys():
           if key.lower() == attr_name_lower:
               return tag.attrs[key]
       return ''
   ```

8. **Namespace-aware parsing**: SVG/MathML elements may have different namespaces. Check tag names case-insensitively.

9. **Style attribute content validation**: The `style` attribute must be in the allowlist to preserve safe CSS, BUT you must validate the CSS content BEFORE the allowlist check. If you add `style` to the allowlist and then check it, dangerous patterns like `expression()` or `behavior:` will slip through. The validation must happen before the allowlist returns True.

10. **SVG animation check order**: Check for dangerous SVG animations BEFORE general attribute filtering. If you filter attributes first, the dangerous values get stripped but the animation element survives, which may still be exploitable.

## Testing Checklist

- [ ] Script tags (mixed case, entity-encoded)
- [ ] Event handlers (on*, mixed case)
- [ ] javascript: URLs (encoded, obfuscated, with whitespace)
- [ ] data: URIs (embedding HTML/SVG)
- [ ] SVG script elements
- [ ] SVG event handlers (onload on svg/rect/circle)
- [ ] SVG animation (animate, set, animateTransform with dangerous values)
- [ ] SVG use/image with dangerous href
- [ ] SVG foreignObject
- [ ] MathML maction with dangerous actiontype
- [ ] Form action with javascript:
- [ ] Meta refresh with javascript:
- [ ] Base tag hijacking
- [ ] Style attribute with expression()/url(javascript:)
- [ ] Safe content preservation (text, links, images, tables, forms)
- [ ] SVG graphics preservation (shapes, gradients, text)
- [ ] MathML preservation (equations, symbols)

## Tools and Dependencies

- **BeautifulSoup4**: DOM manipulation and sanitization
- **html5lib**: HTML5 parser (implements browser parsing algorithm)

**Deployment requirement:** The script includes automatic dependency installation. It checks for `beautifulsoup4` and `html5lib` on startup and installs them if missing. This ensures the script works in fresh environments without manual setup.

Install manually if needed: `pip install beautifulsoup4 html5lib`

## References

- HTML5 parsing algorithm: https://html.spec.whatwg.org/multipage/parsing.html
- SVG security: https://www.w3.org/TR/SVG/security.html
- MathML security considerations
- XSS prevention cheat sheet: https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
