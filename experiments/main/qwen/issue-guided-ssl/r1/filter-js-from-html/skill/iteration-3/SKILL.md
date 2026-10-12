---
name: filter-js-from-html
description: HTML sanitization skill that removes executable JavaScript behavior while preserving legitimate document structure, SVG/MathML content, forms, and styling
---

# HTML JavaScript Sanitization Skill

## Purpose

Remove executable JavaScript behavior from HTML files while preserving legitimate document structure, visible content, vector graphics (SVG), mathematical equations (MathML), forms, links, and non-dangerous attributes.

## Core Architecture

### Parser Selection

Use **html5lib** when available (browser-compatible HTML5 parsing algorithm), fall back to **html.parser** otherwise. Parser choice is critical because different parsers build different DOM trees for malformed HTML, and parser divergence is the root cause of most sanitizer bypasses.

```python
try:
    import html5lib
    PARSER = "html5lib"
except ImportError:
    PARSER = "html.parser"
```

### Sanitization Pipeline

1. **Parse** the HTML with the selected parser
2. **Remove comments and processing instructions** (can hide payloads)
3. **Remove dangerous container elements** entirely (script, iframe, object, embed, applet, base, frame, frameset, foreignobject)
4. **Detect obfuscated dangerous tags** (tag names with null bytes or control characters that resolve to dangerous names)
5. **Remove meta refresh elements** with dangerous URLs entirely (decompose the entire `<meta>` element, not just strip attributes)
6. **Handle link elements** with dangerous hrefs or rel="import"
7. **Sanitize style elements** containing dangerous CSS
8. **Neutralize dangerous attributes** on all elements:
   - Remove all `on*` event handlers
   - Remove URL attributes with dangerous protocols (javascript:, vbscript:, data:text/html)
   - Remove srcdoc attributes
   - Remove style attributes with dangerous CSS; if cleaning leaves only empty CSS property values (e.g., `background: ;`), remove the entire style attribute
   - Handle SVG-specific href attributes on animation/use elements
   - Remove SMIL animation value attributes (`to`, `from`, `by`, `values`) with dangerous URLs
9. **Serialize** back to HTML
10. **Unwrap fragments** if html5lib added structure to a fragment input

### Fragment Detection

Detect whether input is a fragment (no DOCTYPE, no `<html>`, no `<body>`) vs. a full document. When html5lib parses a fragment, it wraps it in `<html><head><body>`. Extract just the body content for fragments to preserve the original structure.

## Threat Model

See `references/threat_model.md` for the exhaustive list of dangerous tags, attributes, and URL patterns.

## Key Implementation Details

### URL Normalization

Before checking for dangerous protocols, normalize URLs by:
- Removing null bytes, control characters, and whitespace
- Removing HTML entities that might have survived parsing
- Converting to lowercase

This catches obfuscation attempts like:
- `java\x09script:` (tab in protocol)
- `java\nscript:` (newline in protocol)
- `java&#x73;cript:` (entity-encoded characters)

### Tag Name Obfuscation

Check if tag names contain control characters or Unicode replacement characters (U+FFFD) that, when removed, resolve to dangerous tag names. This catches:
- `<scr\x00ipt>` (null byte in tag name)
- `<i\x00frame>` (null byte in tag name)

### CSS-based Execution

Check both inline `style` attributes and `<style>` element content for:
- `expression()` (IE)
- `javascript:` in `url()` (handle nested parentheses in url values like `url(javascript:alert(1))`)
- `-moz-binding` (XBL)
- `behavior:` (HTC)

When cleaning dangerous CSS from `style` attributes, if only empty property declarations remain (e.g., `background: ;` or `background:`), remove the entire style attribute. A CSS property with an empty value is functionally meaningless.

### SVG/MathML Namespace Handling

SVG and MathML elements can contain executable content:
- `<script>` inside `<svg>` or `<math>`
- Event handlers on any SVG/MathML element
- SMIL animation elements (`<animate>`, `<set>`, etc.) with dangerous URL attributes (`xlink:href`, `to`, `from`, `by`, `values`)
- `<use>` and `<feImage>` with dangerous hrefs
- `<foreignObject>` — **remove entirely** (parser divergence risk: embeds HTML inside SVG context where sanitizer and browser may build different DOM trees)
- `<style>` elements with dangerous CSS

## Preservation Fidelity

The filter preserves:
- Document structure (DOCTYPE, html, head, body)
- Safe attributes (class, id, data-*, style without dangerous CSS)
- Safe URLs (https:, http:, relative paths)
- SVG graphics (shapes, paths, text, safe styles)
- MathML equations
- Forms with safe actions
- Tables, lists, semantic HTML
- Images with safe src
- Links with safe hrefs

## Edge Cases

- **Case variations**: `<ScRiPt>`, `<IMG OnErRoR=...>` — always compare lowercase
- **Entity encoding**: `href="java&#x73;cript:..."` — parser decodes entities
- **Null bytes**: `<scr\x00ipt>` — detect and remove obfuscated tags
- **Fragment inputs**: Unwrap html5lib-added structure
- **Mixed safe/unsafe**: Preserve safe parts while removing dangerous parts
- **Nested dangerous content**: Recursively sanitize (e.g., foreignObject)

## Usage

```bash
python3 filter.py <html_file>
```

Modifies the file in-place.
