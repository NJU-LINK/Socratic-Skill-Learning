---
name: filter-js-from-html
description: |
  Remove executable JavaScript and dangerous content from HTML files while preserving
  safe document structure, visible content, and formatting. Handles script tags, event
  handlers, javascript: URLs, CSS url() vectors, data: URLs, SVG/MathML animation
  vectors, meta refresh, and nested obfuscation (entities, tabs, percent-encoding).
---

# Filter JavaScript from HTML

## Overview

Sanitize HTML documents by removing executable JavaScript while preserving safe content.
Handles:

- **Executable vectors**: script tags, event handlers, javascript: URLs, CSS url()
- **Preservation**: document structure, visible content, forms, images, safe styles, entities
- **Obfuscation**: entity-encoded payloads, tab/newline injection, whitespace variations
- **Browser fidelity**: void elements, nested containers, self-closing tags

## Architecture: Parse, Never Regex

**Critical**: Never use regex or string replacement for HTML sanitization. Regex fails on:
- Entity-encoded content (`&#106;avascript:`)
- Tab/newline injection (`java\tscript:` - browsers strip these before parsing)
- Case variation (`JaVaScRiPt:`)
- Reassembly attacks (`<scr<script>ipt>` - naive removal creates the tag)

**Solution**: Use a real HTML parser. Python's `html.parser` from stdlib is available
but has limitations (no foreign-content rules for SVG/MathML). Compensate by being
conservative in ambiguous contexts.

## State Machine: Stack-Based Drop Regions

**Critical bug class**: Single-tag drop tracking fails on nested containers.
```html
<object><iframe>x</iframe></object><p>survives?</p>
```
With single `drop_tag`, the `</iframe>` doesn't match `object`, drop state never exits,
and `<p>survives?</p>` is swallowed.

**Fix**: Use a stack, not a single tag:
```python
def __init__(self):
    self.drop_stack = []      # Stack of tags being dropped
    self.preserve_stack = []  # Stack of raw-text elements

def handle_starttag(self, tag, attrs):
    if should_drop(tag, attrs):
        self.drop_stack.append(tag.lower())
        return

def handle_endtag(self, tag):
    if self.drop_stack and tag.lower() == self.drop_stack[-1]:
        self.drop_stack.pop()
```

## Void vs Container Element Handling

**HTML Void Elements** (never have end tags):
```
area, base, br, col, embed, hr, img, input,
link, meta, param, source, track, wbr
```

**Critical bug class**: Dropping void elements with container logic causes the drop state
to never exit, swallowing all following content to EOF.

**Rule**: Partition dangerous element logic:
- Container elements: drop start→matching end, track with stack for nesting
- Void elements: drop tag only, NO state change

## Danger Inventory

### Elements to Drop (with content until matching end tag)

**Category rule**: Elements that embed a nested document/browsing context get dropped 
wholesale; sanitizing their contents is never sufficient.

- `<script>` - executable code
- `<iframe>` - embeds nested browsing context
- `<object>`, `<applet>` - plugin containers
- `<frame>`, `<frameset>`, `<noframes>` - legacy frames
- `<foreignObject>` - SVG HTML integration point (embeds arbitrary HTML)
- `<annotation-xml>` - MathML HTML integration point (encoding="text/html")
- `<animate>`, `<set>`, etc. - **when dangerous** (see SVG Animation section)

### Void Elements to Drop (tag only)

- `<embed>` - embeds plugins
- `<meta>` - **only when** `http-equiv="refresh"` with dangerous URL

### Event Handlers

Remove ALL `on*` attributes (case-insensitive).

**Context-free rule**: Apply everywhere - SVG, MathML, foreignObject, etc. The context
(forbidding mode) is complex; context-free removal is safer and simpler.

### URL Attributes

Check for executable schemes in:
- `href`, `src`, `action`, `formaction`, `poster`
- `xlink:href` (SVG)

**URL normalization** (browsers do this):
1. Strip ASCII tabs (9), newlines (10), CR (13), null (0)
2. Strip leading whitespace/control chars
3. Lowercase for scheme detection
4. Check for `javascript:`, `vbscript:`, `data:text/html...`

**Note**: html.parser decodes entities in attribute values automatically.

### CSS Style Attributes

**Style elements** (`<style>`): Preserve verbatim - CSS content is not executable in modern browsers.

**Style attributes**: Scan for `url(...)` with dangerous schemes:
```python
def has_dangerous_css_url(style_value):
    url_pattern = r'url\s*\(\s*["\']?([^\)"\']+)["\']?\s*\)'
    for url in re.findall(url_pattern, style_value, re.I):
        if dangerous_url(url):  # Same normalization
            return True
    return False
```

Drop the entire `style` attribute if it contains dangerous URLs.

### Meta Refresh

Use regex to handle whitespace variations:
```python
match = re.search(r'url\s*=\s*(.+)', content, re.I)
if match:
    return dangerous_url(match.group(1).strip().strip('"\''))
```

Matches: `url=/path`, `URL = /path`, `url =/path`, etc.

### SVG Animation Elements

`<animate>`, `<set>`, etc. are **containers** when dangerous:

- Dangerous if `attributeName="href"` or `"xlink:href"`
- Dangerous if `attributeName` starts with `on`
- Dangerous if `to`/`from`/`by`/`values` contains dangerous URL

**Implementation**: 
- Check danger condition in `handle_starttag`
- If dangerous, push to `drop_stack` (treat as container)
- If safe, process normally
- For self-closing form (`<set ... />`), drop tag only

### Data: URLs

- Dangerous: `data:text/html,...`, `data:image/svg+xml,...` in navigational context
- Safe: `data:image/png,...`, `data:image/jpeg,...`

## Attribute Handling

### Duplicate Attributes - Security Critical

Browsers use the **first** occurrence. A dict keeps the **last**, creating a bypass:
```html
<a href="javascript:alert(1)" href="/safe">  # Browser executes javascript:
```

**Implementation**: Iterate attrs list, track seen names (lowercased), skip duplicates,
keep first. This is the **security-critical step**.

## Raw Text Elements

Browsers treat `<tag/>` as opening tag (ignore the `/`) for:
```
script, style, noembed, noframes, xmp, iframe
```

**script**: Content is executable - DROP until `</script>` or EOF
**style**: Content is CSS (safe) - PRESERVE until `</style>` or EOF  
**iframe**: Content is fallback text - DROP until `</iframe>` or EOF

**Idempotency pitfall**: Default `handle_startendtag` calls `handle_starttag` then 
`handle_endtag`, emitting synthetic end tags. Override it to avoid spurious `</script>`
in output.

## Iframe Srcdoc

**Design decision**: This implementation drops iframe wholesale. The `srcdoc` attribute
contains HTML that would need recursive sanitization, but since iframe itself is removed,
this is moot. 

**Variant consideration**: If preserving iframes, recursively sanitize `srcdoc` content
before emitting. This requires the same filter class instantiated recursively.

## Verification Checklist

- **Idempotency**: `filter(filter(x)) == filter(x)`
- **Nested containers**: `<object><iframe>...</iframe></object><p>survives</p>`
- **CSS bad**: `<div style="background:url(javascript:...)">` → style removed
- **CSS good**: `<p style="color: red">` → preserved
- **Meta refresh**: `URL = javascript:...` → meta removed
- **Set container**: `<set attr=...>content</set>` → all removed
- **Entity href**: `jav&#x61;script:` in href → href removed
- **Safe data**: `data:image/png` → preserved
- **Foreign object**: `<foreignObject>...</foreignObject>` → removed entirely
- **Annotation XML**: `<annotation-xml encoding="text/html">...</annotation-xml>` → removed entirely
- **Self-closing idempotency**: `<br/><hr/>` stays identical

## Common Pitfalls

1. **Void element state machine**: Entering drop state for void elements causes content loss
2. **Nested containers**: Single-tag tracking fails; must use stack
3. **Synthetic end tags**: Default `handle_startendtag` breaks idempotency
4. **Case sensitivity**: `ONCLICK` and `onclick` are equivalent
5. **URL normalization**: Browsers strip control chars before scheme check
6. **CSS url()**: Can contain `javascript:` - check style attributes
7. **Meta refresh whitespace**: `URL = javascript:` vs `url=javascript:`
8. **Animation elements**: Are containers, not void elements
9. **First-wins duplicate attrs**: Dict loses to browser's first-wins semantics
10. **HTML embedding elements**: `foreignObject`, `annotation-xml` - drop entirely, don't just sanitize contents

## Dependencies

Python stdlib only: `html.parser`, `html.escape`, `re`
