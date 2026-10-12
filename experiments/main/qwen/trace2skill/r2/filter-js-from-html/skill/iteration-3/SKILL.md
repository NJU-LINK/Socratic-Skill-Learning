---
name: filter-js-from-html
description: General starting point for solving tasks in the filter-js-from-html family.
---

# filter-js-from-html

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Key Sanitization Rules

### Meta & Navigation Tags
- **`<meta http-equiv="refresh">` and `<base>`**: If they contain dangerous URLs (e.g., `javascript:`), remove the **entire element** from the DOM. Do not merely strip the `content` or `href` attribute.
- **Meta Refresh Parsing**: BeautifulSoup decodes HTML entities (e.g., `jav&#x61;script:`), so match against the decoded string. Do not rely on strict `url=` prefix matching; browsers tolerate whitespace (e.g., `URL = javascript:...`). Use a regex like `/url\s*=\s*/i` or check the portion after the first semicolon for dangerous URI schemes.

### SVG Elements & Attributes
- **`<foreignObject>`**: Must be completely removed (decomposed) along with all its children. It acts as an HTML-in-SVG bridge and is inherently dangerous.
- **SVG Animation Attributes**: Sanitize value attributes (`to`, `from`, `by`, `values`) on SVG animation elements (`<animate>`, `<set>`, `<animateTransform>`). If the `attributeName` targets a URI attribute (e.g., `xlink:href`, `href`), these values can contain executable `javascript:` URIs. Strip or neutralize them.

### CSS and Style Attributes
- **Dangerous CSS Patterns**: If a `style` attribute value contains dangerous patterns like `url(javascript:...)`, `expression()`, `-moz-binding`, or `behavior`, remove the **entire `style` attribute**.
- Do NOT use regex substitution to strip only the dangerous substring. The removal must be binary: if dangerous, drop the whole attribute.
- For `<style>` element bodies, remove the entire dangerous declaration (`property:value;`), not just the dangerous token.