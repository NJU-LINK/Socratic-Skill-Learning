---
name: filter-js-from-html
description: >
  Sanitize HTML files by removing all executable JavaScript behavior while
  preserving legitimate document structure, visible content, vector graphics,
  equations, forms, links, and non-dangerous attributes. Covers script tags,
  inline event handlers, dangerous URL protocols, data URLs, SVG/MathML
  execution vectors, CSS-based attacks, and encoding-based evasion techniques.
---

# HTML JavaScript Sanitizer

## Task Overview

Create a Python script (`/app/filter.py`) that takes an HTML file path as
`argv[1]`, removes all executable JavaScript behavior, and writes the
sanitized result back to the same file (in-place modification).

The sanitizer must be **comprehensive** (block all known JS execution vectors)
and **conservative** (preserve all safe content and functionality).

## Environment

- Python 3.13+ with `beautifulsoup4` (html.parser backend) and `soupsieve`
- No lxml or html5lib available — use `html.parser` as the BS4 parser
- pytest for testing; selenium/chromium may be used for browser-based verification

## Implementation Strategy

### 1. Parser Choice and Behavior

Use **BeautifulSoup with `html.parser`**. Key behaviors:

| Behavior | Implication |
|---|---|
| Lowercases tag names | `<ScRiPt>` becomes `<script>` |
| **Lowercases ALL attribute names** | `ONCLICK` becomes `onclick`, `attributeName` becomes `attributename` |
| Decodes HTML entities in attrs | `&#106;avascript:` becomes `javascript:` in attribute values |
| Does NOT parse tags inside `<style>` | `<script>` in `<style>` is text — handle separately |
| Does NOT add wrapper tags to fragments | Fragments stay as fragments |
| Tolerant of broken nesting | Auto-corrects |
| Does NOT strip null bytes | `<scr\x00ipt>` becomes text — must preprocess |

### 2. Preprocessing (Before Parsing)

Strip null bytes and control characters (0x00-0x08, 0x0B, 0x0C, 0x0E-0x1F,
0x7F) from the raw HTML before parsing.

### 3. Sanitization Phases

#### Phase 1: Remove Inherently Dangerous Tags (decompose entire subtree)

`script`, `iframe`, `object`, `embed`, `applet`, `frame`, `frameset`

#### Phase 2: SVG-Specific Dangers

- **`foreignObject`** — decompose (can embed arbitrary HTML including scripts)
- **SVG animation elements** (`animate`, `set`, `animateTransform`,
  `animateMotion`, `animateColor`) — dangerous when `attributeName` targets:
  event handler attrs, URL-bearing attrs with javascript:, or `style` with dangerous CSS
- Safe SVG animations (e.g., `attributeName="x"`, `attributeName="fill"`)
  must be **preserved**
- Read `attributename` (lowercase) since BS4 lowercases all attribute names

#### Phase 3: Meta Refresh — CRITICAL: Handle Whitespace Variations

Remove `<meta http-equiv="refresh">` when `content` contains a dangerous URL.
The content format is `<delay>; url = <target_url>` where **the `url =` part
can have arbitrary whitespace around it**.

Examples that MUST all be detected:
- `content="0;url=javascript:alert(1)"` — no spaces
- `content="0; URL = javascript:alert(1)"` — spaces around =
- `content="0;url = javascript:alert(1)"` — space after =
- `content="0; URL =jav&#x61;script:alert(1)"` — entity + spaces (BS4 decodes entities in attrs)

**DO NOT use** `'url=' in content.lower()` — this fails with spaces around `=`.

**Use a whitespace-tolerant regex AND normalization fallback:**

```python
def sanitize_meta_refresh(meta_tag):
    content = meta_tag.get('content', '')
    if isinstance(content, list):
        content = ' '.join(content)
    content = str(content)
    
    # Regex with \s* to tolerate whitespace around url=
    match = re.search(r';\s*url\s*=\s*(.+)', content, re.IGNORECASE)
    if match:
        url_part = match.group(1).strip().strip("'\"")
        if is_dangerous_url(url_part):
            return True
    
    # Fallback: normalize entire content (unescape + strip controls + collapse ws)
    # Then check if dangerous protocol appears anywhere
    normalized = normalize_for_protocol_check(content)
    if 'javascript:' in normalized.lower() or 'vbscript:' in normalized.lower():
        return True
    
    return False
```

#### Phase 4: Base Tag
Remove `<base>` with dangerous `href`. Keep safe base tags.

#### Phase 5: Link Tags
Remove `<link>` with dangerous `href`. Keep safe link tags.

#### Phase 6: Style Tag Content
Clean `<style>` text: remove embedded HTML tags, dangerous CSS patterns
(`expression()`, `javascript:` URLs, `-moz-binding`, `behavior`), and
dangerous `@import` statements.

#### Phase 7: Attribute Sanitization (all remaining elements)

1. **Remove event handler attributes** — `^on[a-z]` (case-insensitive)
2. **Remove dangerous URL-bearing attributes entirely** — `href`, `src`, `action`,
   `formaction`, `data`, `poster`, `background`, `dynsrc`, `lowsrc`,
   `srcdoc`, `xlink:href`, `ping`, `cite`, `usemap`, `longdesc`
3. **Remove dangerous `style` attributes ENTIRELY** — if
   `is_dangerous_style(value)` is True, delete the whole attribute.
   **DO NOT** attempt partial regex-based CSS stripping — regex on
   `url(...)` fails with nested parentheses, leaving fragments behind.

#### Phase 8: Dangerous Comments
Remove IE conditional comments. Preserve regular comments.

### 4. URL Protocol Checking

Normalize before checking:
1. `html.unescape(value)` — decode entities
2. Strip null/control chars
3. Collapse all whitespace
4. Check dangerous protocols: `javascript:`, `vbscript:`, `livescript:`

Data URL handling: block `data:image/svg+xml`, `data:text/html`, and all
data: not explicitly safe. Allow `data:image/{png,jpeg,jpg,gif,webp,bmp,x-icon};base64,...`

### 5. Style Attribute Checking

Binary decision function — if ANY dangerous CSS pattern matches, remove the
entire attribute. Decode HTML entities first, then check patterns
(case-insensitive): `expression\s*\(`, `javascript\s*:`, `vbscript\s*:`,
`-moz-binding\s*:`, `behavior\s*:`, `url\s*\(\s*["']?\s*(javascript|vbscript|data:text/html)`

### 6. Encoding Evasion Techniques

| Technique | Defense |
|---|---|
| Case variation | BS4 lowercases; `re.IGNORECASE` |
| HTML entities (decimal/hex) | `html.unescape()` |
| Double encoding | `html.unescape()` twice |
| Null bytes | Strip before parsing |
| Whitespace in protocols | Collapse whitespace before check |
| Newline/tab injection | Collapse whitespace before check |
| Whitespace in meta refresh `url =` | Use `\s*` in regex or normalize entire content |

### 7. Preservation Rules

Preserve: document structure, semantic HTML, tables, forms, links, images,
SVG, MathML, safe attributes, safe style attrs, text, safe comments,
safe CSS blocks, safe meta/base/link tags.

Remove entirely (not partially): dangerous style attrs, dangerous URL attrs,
event handler attrs, dangerous tags.

### 8. Output Format

BS4 `str(soup)`. Fragments stay fragments. Self-closing tags may expand.
Attribute names lowercased by BS4 — acceptable.

## Verification Checklist

- [ ] `<script>` removed (mixed case, with attrs)
- [ ] `onclick`, `onerror`, etc. removed
- [ ] `javascript:` URLs blocked in href, src, action, formaction, etc.
- [ ] `style="...javascript:..."` → **entire style attr removed**
- [ ] Safe style preserved
- [ ] Entity-encoded URLs decoded and blocked
- [ ] Whitespace-obfuscated URLs normalized and blocked
- [ ] `data:text/html` blocked; `data:image/png;base64` preserved
- [ ] iframe, object, embed, applet removed
- [ ] SVG foreignObject removed
- [ ] SVG animate with dangerous attributeName removed; safe kept
- [ ] `<meta http-equiv="refresh" content="0;url=javascript:...">` removed
- [ ] **`<meta http-equiv="refresh" content="0; URL = javascript:...">` removed** (spaces around =)
- [ ] `<base href="javascript:...">` removed
- [ ] Style tag content cleaned
- [ ] Null-byte obfuscation handled
- [ ] Safe content preserved
- [ ] Template scripts sanitized
- [ ] IE conditional comments removed
- [ ] In-place modification via argv[1]

## Common Pitfalls

1. **Meta refresh whitespace (CRITICAL)** — `'url=' in content.lower()`
   fails for `URL = javascript:...`. Use regex `r';\s*url\s*=\s*(.+)'`
   with `re.IGNORECASE`, or normalize entire content after collapsing
   whitespace.

2. **Partial style sanitization** — remove entire attr when dangerous,
   don't try regex-based CSS stripping. `url\s*\([^)]*\)` fails on
   nested parens like `url(javascript:alert(1))`.

3. **Null bytes** — strip before parsing.

4. **xlink:href** — check in SVG elements.

5. **formaction** — check in button/input elements.

6. **Style tag text** — handle embedded `<script>` as text.

7. **SVG animations** — only remove if attributeName targets danger.
   BS4 lowercases `attributeName` to `attributename`.

8. **Protocol normalization** — collapse whitespace before check.

9. **Data URLs** — allow safe raster images.

10. **BS4 list attrs** — join before checking.

11. **BS4 lowercases attrs** — use lowercase keys for lookups.
