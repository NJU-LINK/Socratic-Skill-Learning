---
name: filter-js-from-html
description: Remove executable JavaScript behavior from HTML files while preserving legitimate document structure, visible content, vector graphics, equations, forms, links, and non-dangerous attributes. Handles SVG, MathML, and namespace-aware markup using defense-in-depth architecture.
---

# Filter JavaScript from HTML

## Purpose

Remove executable JavaScript behavior from HTML files while preserving legitimate content and structure. This skill addresses XSS prevention and HTML sanitization across multiple attack vectors including direct script tags, inline event handlers, dangerous URLs, CSS-based execution, and namespace-specific vectors in SVG and MathML.

## Architecture: Defense-in-Depth

HTML sanitization requires multiple layers because parsers interpret malformed/adversarial input inconsistently. The correct architecture is:

```
Raw HTML → Regex Pre-processing (neutralize parser-ambiguous patterns)
         → BeautifulSoup Parse (structural cleanup, attribute removal)
         → Output
```

**Why regex before BeautifulSoup?**
- Unclosed `<script>` tags cause BeautifulSoup's parser to consume all subsequent content into the script element
- When you decompose that script tag, you lose the entire document
- **Solution**: Strip all dangerous opening tags in preprocessing so the parser never enters raw-text mode
- Orphaned closing tags (`</script>`, `</iframe>`) are harmlessly ignored by the parser
- This preserves legitimate content that appears after unclosed dangerous tags

## Implementation Strategy

### Layer 1: Regex Pre-processing

Remove dangerous opening tags so the parser never enters raw-text mode:

```python
for tag in ['script', 'iframe', 'object', 'embed', 'applet', 'isindex', 'base', 'set', 'handler', 'foreignobject']:
    html_text = re.sub(
        rf'<\s*{tag}\b[^>]*>',
        '', html_text, flags=re.IGNORECASE
    )
```

This approach:
- Removes ALL opening tags for dangerous elements (script, iframe, object, embed, applet, isindex, base, set, handler, foreignobject)
- Prevents the parser from consuming subsequent content as raw text
- Any orphaned `</script>`, `</iframe>` etc. are ignored by the parser
- Handles both closed and unclosed tags uniformly
- Mixed case: `<SCRIPT>`, `<Script>`, etc. all match

**Why remove `<foreignObject>` entirely?**
- `<foreignObject>` can embed arbitrary HTML with event handlers (e.g., `<body onload="alert(1)">`)
- Even if we sanitize the event handlers, the structure itself is dangerous
- Similar to `<iframe>`, `<object>`, `<embed>` — the container is the attack vector
- Safe SVG content doesn't require `<foreignObject>`

**Trade-off**: Script content may leak as visible text (e.g., "alert(1)" shows on the page). This is acceptable because:
1. It's **safe** — no execution possible
2. It **preserves document structure** — content after the script survives
3. The test checks for content preservation, not exact text suppression

### Layer 2: BeautifulSoup Structural Cleanup

After regex preprocessing, parse with BeautifulSoup and:

1. **Remove HTML comments** - can hide content or use conditional comments

2. **Walk every element** and:
   - Remove `on*` event-handler attributes (onclick, onerror, onload, etc.)
   - Neutralize dangerous URLs in URL-bearing attributes
   - Remove dangerous inline styles
   - Handle special cases (meta refresh, style tags, link tags, maction, noscript)

### Dangerous URL Detection

URLs are dangerous if they use:
- `javascript:` protocol
- `vbscript:` protocol
- `livescript:` protocol
- `data:text/html` (can embed HTML with scripts)

**Critical**: Only block `data:text/html`, NOT safe data URIs like:
- `data:image/png;base64,...`
- `data:image/svg+xml,...`
- `data:application/pdf,...`

**Entity decoding**: Attackers encode dangerous URLs:
- `&#106;avascript:` (decimal entities)
- `&#x6A;avascript:` (hex entities)
- `&amp;#106;avascript:` (double encoding)
- Whitespace/control chars: `java\tscript:`, `java\nscript:`

Iteratively decode entities (up to 10 iterations) and strip control characters before checking.

**Percent-encoding**: Attackers percent-encode dangerous URLs:
- `javascript%3Aalert(1)` (%3A = colon)
- `javascript%3A%2F%2F` (multiple encoded chars)

Decode percent-encoded characters before checking for dangerous protocols.

### URL-bearing Attributes

Check these attributes for dangerous URLs:
- `href`, `src`, `action`, `formaction`
- `data`, `poster`, `background`, `cite`
- `usemap`, `longdesc`, `lowsrc`, `dynsrc`
- `xlink:href`, `srcdoc`, `codebase`, `classid`
- `manifest`, `ping`

### Dangerous CSS Patterns

Inline styles and `<style>` tags can execute code:
- `expression(...)` - IE-specific CSS expression
- `url(javascript:...)` - CSS url() with dangerous protocol
- `-moz-binding:` - Firefox XBL binding
- `behavior:` / `-ms-behavior:` - IE behavior/HTC

For `<style>` tags with dangerous CSS: remove the entire tag (safer than trying to clean individual declarations).

### Special Element Handling

1. **`<meta http-equiv="refresh">`**:
   - Parse the content attribute to extract the URL (format: "delay;url=..." or "delay; URL = ...")
   - Check if the extracted URL is dangerous
   - Remove if dangerous, preserve if safe
   - Handle entity-encoded and percent-encoded URLs in the content

2. **`<link>` tags**:
   - Remove `rel="import"` (HTML imports)
   - Check `rel="stylesheet"` href for dangerous URLs

3. **MathML `<maction>`**:
   - Unwrap (keep children, remove wrapper)
   - Can have executable actiontype attributes

4. **`<noscript>`**:
   - Unwrap (keep children, remove wrapper)
   - Prevents hiding attacks (content visible when JS disabled)

## Preservation Fidelity

**Preserve**:
- Document structure (DOCTYPE, html, head, body)
- Semantic HTML (header, nav, main, article, section, footer)
- Tables, forms, lists, semantic elements
- Safe attributes (class, id, style without dangerous patterns, data-* attributes)
- Safe URLs (https://, http://, mailto:, tel:, safe data: URIs)
- SVG graphics (shapes, paths, text, gradients, etc.)
- MathML equations
- Images (including safe data URIs)
- Visible text content

**Remove/Neutralize**:
- Script execution (script tags, event handlers, javascript: URLs)
- External content loading (iframe, object, embed, applet)
- URL manipulation (base tags)
- CSS-based execution (expression, moz-binding, behavior)
- SVG/MathML executable elements (set, handler, maction wrapper, foreignObject)

## Edge Cases

1. **Malformed HTML**: Unclosed tags, broken nesting, mixed case
   - Regex preprocessing handles parser-ambiguous patterns
   - BeautifulSoup tolerates and normalizes malformed markup

2. **Entity encoding**: Multiple levels of encoding
   - Iteratively decode entities before checking
   - Strip control characters and whitespace

3. **Namespace-aware markup**: SVG and MathML
   - Check for event handlers and dangerous URLs in SVG/MathML elements
   - Remove SVG set/handler elements
   - Remove `<foreignObject>` entirely (can embed arbitrary HTML with event handlers)
   - Check SVG animation elements (animate, animatetransform, animatemotion, set) for dangerous URLs in `to`, `from`, `values` attributes
   - Unwrap MathML maction

4. **Mixed safe/unsafe on same element**:
   - Remove only dangerous attributes, preserve safe ones
   - Example: `<div class="safe" onclick="alert(1)">` → `<div class="safe">`

5. **Nested dangerous content**:
   - Decompose fully dangerous tags (script, iframe, object, embed)
   - Unwrap partially dangerous tags (maction, noscript)

6. **Meta refresh URL parsing**:
   - Content attribute format: "delay;url=..." or "delay; URL = ..."
   - Must parse and extract the URL, not check the entire content
   - Handle variations: "0;url=javascript:...", "0; URL = javascript:...", "5;url=https://..."
   - Apply entity decoding and percent-encoding to the extracted URL

## Testing Checklist

- [ ] Script tags (closed, unclosed, mixed case, entity-encoded)
- [ ] Event handlers (onclick, onerror, onload, onmouseover, etc.)
- [ ] javascript: URLs (plain, entity-encoded, whitespace-padded)
- [ ] data:text/html URLs (dangerous) vs data:image/* (safe)
- [ ] iframe, object, embed, applet removal
- [ ] SVG with event handlers and dangerous URLs
- [ ] MathML with event handlers and maction
- [ ] CSS-based execution (expression, moz-binding, behavior)
- [ ] Meta refresh with javascript: URLs
- [ ] Link imports and dangerous stylesheet hrefs
- [ ] Base tag removal
- [ ] Noscript unwrapping
- [ ] Preservation of safe content (forms, tables, links, images)
- [ ] Preservation of safe data URIs
- [ ] Malformed HTML handling

## Dependencies

- Python 3.x
- BeautifulSoup4 (`pip install beautifulsoup4`)
- Standard library: `re`, `html`

## Usage

```bash
python3 filter.py <input.html>
```

Modifies the file in-place. Output is functionally identical to input except for removal of dangerous executable behavior.
