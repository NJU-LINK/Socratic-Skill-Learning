# HTML Executable Content Threat Model

This document provides an exhaustive reference of HTML constructs that can cause JavaScript execution and must be neutralized by the sanitizer.

## Dangerous Elements (Remove Entirely)

These elements are execution containers and should be completely removed:

### Script Execution
- `<script>` — Direct JavaScript execution (including inside SVG, MathML, foreignObject)

### Frame/Container Elements
- `<iframe>` — Can load external executable content
- `<frame>` — Frame container (used with frameset)
- `<frameset>` — Frame layout container

### Plugin-based Execution
- `<object>` — Can load plugins, ActiveX, or external content
- `<embed>` — Plugin embedding (Flash, Java, etc.)
- `<applet>` — Java applet (deprecated but still dangerous)

### Navigation/Redirect
- `<base>` — Can redirect all relative URLs to attacker-controlled origin
- `<meta http-equiv="refresh">` with dangerous URL — Navigation-based execution

### HTML Imports
- `<link rel="import">` — HTML imports can load executable content

### SVG Embedded HTML
- `<foreignObject>` — Can embed arbitrary HTML inside SVG context. Parser divergence between sanitizer and browser makes recursive sanitization unreliable; must be removed entirely. An attacker can craft markup that looks safe to the sanitizer but becomes executable when the browser renders it inside the SVG foreign content context.

## Dangerous Attributes

### Event Handlers (on* Attributes)

ALL `on*` attributes must be removed from ALL elements. There are 100+ event handlers:

**Mouse Events:**
- onclick, ondblclick, onmousedown, onmouseup, onmouseover, onmousemove, onmouseout, onmouseenter, onmouseleave

**Keyboard Events:**
- onkeydown, onkeyup, onkeypress

**Form Events:**
- onsubmit, onreset, onchange, oninput, onselect, onfocus, onblur

**Document/Window Events:**
- onload, onunload, onbeforeunload, onerror, onresize, onscroll

**Drag Events:**
- ondrag, ondragend, ondragenter, ondragleave, ondragover, ondragstart, ondrop

**Clipboard Events:**
- oncopy, oncut, onpaste

**Media Events:**
- onabort, oncanplay, oncanplaythrough, ondurationchange, onemptied, onended, onloadeddata, onloadedmetadata, onloadstart, onpause, onplay, onplaying, onprogress, onratechange, onseeked, onseeking, onstalled, onsuspend, ontimeupdate, onvolumechange, onwaiting

**Animation/Transition Events:**
- onanimationstart, onanimationend, onanimationiteration, ontransitionend

**Touch/Pointer Events:**
- ontouchstart, ontouchmove, ontouchend, ontouchcancel, onpointerdown, onpointerup, onpointermove, onpointerover, onpointerout, onpointerenter, onpointerleave, ongotpointercapture, onlostpointercapture

**Other Events:**
- oncontextmenu, oninvalid, onsearch, ontoggle, onwheel, onshow, onpageshow, onpagehide, onhashchange, onpopstate, onstorage, onmessage, ononline, onoffline

**Rule:** If an attribute name starts with "on" (case-insensitive), remove it.

### URL-bearing Attributes

These attributes can contain `javascript:`, `vbscript:`, or dangerous `data:` URLs:

- `href` — Links, stylesheets, etc.
- `src` — Images, scripts, iframes, media
- `action` — Form submission target
- `formaction` — Button/input form override
- `xlink:href` — SVG XLink (animation, use, feImage)
- `poster` — Video poster image
- `data` — Object data source
- `dynsrc` — Video source (IE)
- `lowsrc` — Low-res image source (IE)
- `background` — Background image (deprecated)
- `value` — Input value (can be dangerous in some contexts)
- `srcdoc` — Inline HTML document for iframe (always dangerous)
- `manifest` — Application manifest
- `ping` — Ping URLs

**SMIL Animation Value Attributes** (can set attributes to dangerous URLs):
- `to` — Animation target value (`<set to=...>`, `<animate to=...>`)
- `from` — Animation starting value
- `by` — Animation relative offset
- `values` — Semicolon-separated list of animation values

These attributes on SMIL elements (`<animate>`, `<animateTransform>`, `<animateMotion>`, `<set>`) can set other attributes to dangerous URLs. Example: `<set attributeName="xlink:href" to="javascript:alert(1)">`

### Dangerous URL Protocols

**javascript:** — Executes JavaScript code
- Case variations: `JavaScript:`, `JAVASCRIPT:`, `JaVaScRiPt:`
- Whitespace/control chars: `java\tscript:`, `java\nscript:`, `java\x00script:`
- Entity encoding: `java&#x73;cript:`, `&#106;avascript:`

**vbscript:** — Executes VBScript (IE)

**data:** with dangerous MIME types:
- `data:text/html,...` — Executes HTML/JS
- `data:image/svg+xml,...` — SVG can contain scripts
- `data:application/xhtml+xml,...` — XHTML can contain scripts

### Style-based Execution

Inline `style` attributes and `<style>` elements can contain:

- `expression()` — IE CSS expression (executes JavaScript)
- `url(javascript:...)` — CSS URL with JavaScript
- `-moz-binding:` — XBL binding (Firefox)
- `behavior:` — HTC behavior (IE)

## SVG-specific Threats

### Script Elements
- `<svg><script>alert(1)</script></svg>` — SVG has its own script element

### SMIL Animation
- `<animate xlink:href="javascript:...">` — Animation triggers JS
- `<animateTransform xlink:href="javascript:...">`
- `<animateMotion xlink:href="javascript:...">`
- `<set xlink:href="javascript:...">` — Set element triggers JS
- `<set attributeName="xlink:href" to="javascript:...">` — Animation sets attribute to dangerous URL via `to`, `from`, `by`, or `values` attributes

### External References
- `<use xlink:href="javascript:...">` — Use element loads external content
- `<feImage xlink:href="javascript:...">` — Filter primitive loads content

### Embedded HTML
- `<foreignObject>` — Can embed arbitrary HTML inside SVG
  - **Remove entirely** (parser divergence between sanitizer and browser makes recursive sanitization unreliable)

### Event Handlers
- Any SVG element can have `on*` event handlers
- `<svg onload="...">`, `<circle onclick="...">`, etc.

### Style Elements
- `<svg><style>body { background: url(javascript:...) }</style></svg>`

## MathML-specific Threats

### Script Elements
- `<math><script>alert(1)</script></math>` — Some browsers execute this

### Event Handlers
- Any MathML element can have `on*` event handlers
- `<mi onclick="...">`, `<math onerror="...">`, etc.

### Dangerous Attributes
- `<mglyph>` with dangerous attributes

## Form-related Threats

### Action Attributes
- `<form action="javascript:...">` — Form submission executes JS
- `<button formaction="javascript:...">` — Button overrides form action
- `<input type="image" src="javascript:...">` — Image input loads JS
- `<input type="submit" formaction="javascript:...">`

### Input Types
- `<input type="image">` — Can have dangerous src

## Meta/Link Threats

### Meta Refresh
- `<meta http-equiv="refresh" content="0;url=javascript:...">`
- `<meta http-equiv="refresh" content="0;url=data:text/html,...">`

### Link Elements
- `<link href="javascript:...">` — Link with JavaScript URL
- `<link rel="import" href="...">` — HTML import loads executable content
- `<link rel="prefetch" href="javascript:...">` — Prefetch with JavaScript

## Obfuscation Techniques

### Case Variation
- `<ScRiPt>`, `<IMG SRC=x OnErRoR=...>`
- Always compare tag/attribute names in lowercase

### Whitespace/Control Characters
- `<img on\x09error=...>` (tab in attribute name)
- `<a href="java\nscript:...">` (newline in protocol)
- `<scr\x00ipt>` (null byte in tag name)

### Entity Encoding
- `href="java&#x73;cript:..."` (hex entity)
- `href="&#106;avascript:..."` (decimal entity)
- `href="java&Tab;script:..."` (named entity)

### Null Bytes
- `<scr\x00ipt>` — Browsers may strip null bytes
- Parsers replace null bytes with U+FFFD (replacement character)

### Fragmented Payloads
- Split across multiple attributes or nodes
- Requires normalization before detection

### Layered Encoding
- Double-encoded entities
- URL-encoded entities
- Requires multiple decoding passes

## Parser Divergence

Different parsers build different DOM trees for malformed HTML:

### SVG/HTML Namespace Confusion
- `<svg><desc><img src=x onerror=alert(1)></desc></svg>`
  - Some parsers treat `<desc>` content as text
  - Browsers may render it as HTML if namespace handling differs

### Broken Nesting
- Unclosed tags, misnested elements
- html5lib follows HTML5 spec; html.parser is more lenient

### Template Elements
- `<template>` content is inert but can be activated by surviving JS

### Noscript Elements
- `<noscript>` content isn't rendered in JS-enabled context
- But should still be sanitized

## Safe Content (Preserve)

The following should be preserved unchanged:

- Document structure (DOCTYPE, html, head, body)
- Semantic HTML (header, nav, main, article, section, footer)
- Tables (table, tr, td, th, thead, tbody, tfoot)
- Lists (ul, ol, li, dl, dt, dd)
- Forms with safe actions (action="/submit", method="post")
- Safe attributes (class, id, data-*, title, alt, etc.)
- Safe URLs (https:, http:, relative paths, mailto:)
- Images with safe src (image files, data:image/png, etc.)
- Links with safe hrefs
- SVG graphics (shapes, paths, text, safe styles, animations without JS)
- MathML equations
- Safe CSS (colors, fonts, layouts, backgrounds with safe URLs)
- Media elements with safe sources (video, audio with http/https src)
- Safe meta tags (charset, viewport, description)
- Safe link elements (stylesheet, icon, canonical)

## Testing Checklist

When validating the sanitizer, test:

1. ✓ Basic script tag removal
2. ✓ Event handler removal (all on* attributes)
3. ✓ javascript: URL removal (with obfuscation)
4. ✓ SVG script removal
5. ✓ SVG animation with dangerous href
6. ✓ MathML script/event handler removal
7. ✓ iframe/object/embed removal
8. ✓ base tag removal
9. ✓ meta refresh with dangerous URL
10. ✓ link with dangerous href/rel
11. ✓ Style-based execution (expression, url(javascript:))
12. ✓ Form action with javascript:
13. ✓ Fragment input handling
14. ✓ Full document input handling
15. ✓ Case variations
16. ✓ Entity-encoded payloads
17. ✓ Null byte obfuscation
18. ✓ Whitespace/control char obfuscation
19. ✓ Safe content preservation
20. ✓ Mixed safe/unsafe content
