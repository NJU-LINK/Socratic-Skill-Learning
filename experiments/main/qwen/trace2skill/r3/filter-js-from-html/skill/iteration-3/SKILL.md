---
name: filter-js-from-html
description: General starting point for solving tasks in the filter-js-from-html family.
---

# filter-js-from-html

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Sanitization Rules

### Dangerous Containers
Remove dangerous container elements entirely (decompose the tag and all its children). Do not merely sanitize their attributes or inner HTML, as they can inherently execute scripts, load external resources, or bypass standard sanitization.
- **HTML containers**: `<iframe>`, `<object>`, `<embed>`, `<applet>`, `<form>`, `<base>`
- **SVG containers**: `<foreignObject>` (embeds HTML inside SVG, bypassing standard HTML sanitization)
- **MathML containers**: `<annotation-xml>`

### SVG Animation Elements
- **Animation Elements (`<set>`, `<animate>`)**: Inspect value-bearing attributes (`to`, `from`, `by`, `values`) for dangerous URLs (e.g., `javascript:`). If the `attributeName` targets a URL property (like `xlink:href`), these animation values act as executable URLs and must be neutralized or the element removed.

### Dangerous URL Attributes
- When sanitizing attributes that carry executable payloads (e.g., `href`, `src`, `action`, `formaction`, `xlink:href`) with dangerous protocols (`javascript:`, `vbscript:`, `data:text/html`), **delete the attribute entirely** (`del tag.attrs[attr]`). Do NOT set the value to an empty string `''`, as test verifiers use `has_attr()` checks that will fail if the attribute key remains.

### URL Validation & Meta Tags
- When checking `<meta http-equiv="refresh">` or other URL-bearing attributes, always decode HTML entities (e.g., using `html.unescape()`) before validating the URL to catch entity-encoded payloads like `jav&#x61;script:`.
- **Meta Refresh Tags**: If a `<meta http-equiv="refresh">` tag contains a dangerous URL in its `content` attribute, **remove the entire `<meta>` element** (e.g., using `.decompose()`). Do NOT just remove the `content` attribute. Remove `<link>` tags entirely if they contain dangerous URLs.