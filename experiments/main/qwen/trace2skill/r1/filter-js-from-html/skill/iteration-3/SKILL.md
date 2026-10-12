---
name: filter-js-from-html
description: General starting point for solving tasks in the filter-js-from-html family.
---

# filter-js-from-html

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Sanitization Rules

When filtering executable vectors from HTML/SVG, apply these specific rules:

- **Dangerous URL Attributes**: When an attribute contains a dangerous URL (e.g., `javascript:`, `vbscript:`, `data:text/html`), delete the attribute entirely. Do not replace the value with placeholders like `about:blank` or `#`.
- **`<foreignObject>`**: Decompose (remove entirely with all children). Do not attempt to clean its inner HTML, as it embeds a full HTML context inside SVG where browser parsing can reintroduce executable behavior.
- **`<use>`, `<a>`, `<image>`**: If these elements contain dangerous attributes (e.g., `href` or `xlink:href`), strip the dangerous attribute only. Do NOT decompose the entire element.
- **SVG Animation / SMIL Elements**: Elements like `<set>`, `<animate>`, `<animateMotion>`, `<animateTransform>`, and `<animateColor>` can dynamically inject executable content. Decompose (remove) these elements entirely.
- **CSS `style` Attributes**: When sanitizing `style` attributes (e.g., removing `url(javascript:...)` or `expression(...)`), verify that meaningful CSS remains. If the cleaned string contains only empty property declarations or lacks valid `property: value` pairs, remove the entire `style` attribute.
