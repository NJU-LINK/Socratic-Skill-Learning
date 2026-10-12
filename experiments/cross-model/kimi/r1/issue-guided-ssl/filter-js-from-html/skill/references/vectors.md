# HTML/SVG JavaScript Execution Vector Taxonomy

This document catalogs known JavaScript execution vectors in HTML, SVG, and MathML, with expected sanitizer behavior.

## HTML Vectors

### Script Elements

**Direct script block**
```html
<script>alert(1)</script>
```
**Expected:** Drop entire subtree.

**External script**
```html
<script src="http://evil.com/payload.js"></script>
```
**Expected:** Drop entire subtree.

**Mixed case tag**
```html
<ScRiPt>alert(1)</ScRiPt>
```
**Expected:** Drop entire subtree (case-insensitive match).

### Event Handlers

**Standard handlers**
```html
<img src="x" onerror="alert(1)">
<button onclick="alert(1)">
<body onload="alert(1)">
```
**Expected:** Strip event handler attribute, keep element.

**Vendor-prefixed/future handlers**
```html
<div ontoggle="alert(1)">
<div onsecuritypolicyviolation="alert(1)">
```
**Expected:** Strip any attribute starting with `on` (case-insensitive).

### JavaScript URLs

**Anchor href**
```html
<a href="javascript:alert(1)">Click</a>
```
**Expected:** Strip href attribute, keep link text.

**Tab-obfuscated**
```html
<a href="jav&#9;ascript:alert(1)">Click</a>
<a href="jav\tascript:alert(1)">Click</a>
```
**Expected:** Strip href (TAB/LF/CR removed before scheme check).

**Form action**
```html
<form action="javascript:alert(1)">
```
**Expected:** Strip action, keep form and contents.

**Button formaction**
```html
<button formaction="javascript:alert(1)">Submit</button>
```
**Expected:** Strip formaction, keep button.

**Base href**
```html
<base href="javascript:alert(1)">
```
**Expected:** Strip href (dangerous, affects all relative URLs).

**Area href**
```html
<area href="javascript:alert(1)">
```
**Expected:** Strip href.

### data: URL Vectors

**data:text/html in navigation (href)**
```html
<a href="data:text/html,<script>alert(1)</script>">Click</a>
<a href="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">Click</a>
```
**Expected:** Strip href (data: blocked in navigation contexts).

**data:image/png in resource (img src)**
```html
<img src="data:image/png;base64,iVBORw0KGgo...">
```
**Expected:** Keep (passive image allowed in resource context).

**data:text/html in resource**
```html
<object data="data:text/html,<script>alert(1)</script>">
```
**Expected:** Strip data attribute (data:text/html never allowed).

### Embedding Elements

**Iframe**
```html
<iframe src="evil.html"></iframe>
<iframe src="javascript:alert(1)"></iframe>
<iframe srcdoc="<script>alert(1)</script>"></iframe>
```
**Expected:** Drop entire subtree.

**Object (dangerous data)**
```html
<object data="javascript:alert(1)">
  <p>Fallback content</p>
</object>
```
**Expected:** Strip data attribute, keep object and fallback content.

**Object (safe data)**
```html
<object data="movie.swf">
  <p>Fallback content</p>
</object>
```
**Expected:** Keep data attribute and all content.

**Embed**
```html
<embed src="javascript:alert(1)">
```
**Expected:** Strip src attribute (void element, no fallback).

### Meta Refresh

**JavaScript URL in refresh**
```html
<meta http-equiv="refresh" content="0;url=javascript:alert(1)">
<meta http-equiv="refresh" content="5; URL=javascript:alert(1)">
```
**Expected:** Drop entire meta tag.

**Safe refresh**
```html
<meta http-equiv="refresh" content="5;url=/home">
```
**Expected:** Keep (safe HTTP URL).

### Duplicate Attributes

**Dangerous first value**
```html
<a href="javascript:alert(1)" href="https://safe.com">Link</a>
```
**Expected:** Strip href entirely (first value is dangerous).

**Safe first value**
```html
<a href="https://safe.com" href="javascript:alert(1)">Link</a>
```
**Expected:** Keep href="https://safe.com" (first value wins).

## SVG Vectors

### SVG Event Handlers

**onload on SVG element**
```html
<svg onload="alert(1)">
  <circle cx="50" cy="50" r="40"/>
</svg>
```
**Expected:** Strip onload, keep SVG and children.

**onclick on SVG element**
```html
<svg>
  <circle onclick="alert(1)" cx="50" cy="50" r="40"/>
</svg>
```
**Expected:** Strip onclick, keep circle.

### SVG Script Element

**Script inside SVG**
```html
<svg>
  <script>alert(1)</script>
</svg>
```
**Expected:** Drop script subtree, keep SVG.

### XLink href

**JavaScript in xlink:href**
```html
<svg>
  <a xlink:href="javascript:alert(1)">Click</a>
</svg>
```
**Expected:** Strip xlink:href, keep link.

**Safe xlink:href**
```html
<svg>
  <a xlink:href="https://example.com">Click</a>
</svg>
```
**Expected:** Keep xlink:href.

### SVG SMIL Animation

**Animating href to JavaScript**
```html
<svg>
  <rect width="100">
    <animate attributeName="href" values="javascript:alert(1)" />
  </rect>
</svg>
```
**Expected:** Drop animate element.

**Animating xlink:href**
```html
<svg>
  <rect>
    <animate attributeName="xlink:href" values="javascript:alert(1)" />
  </rect>
</svg>
```
**Expected:** Drop animate element.

**Animating event handler**
```html
<svg>
  <rect>
    <animate attributeName="onmouseover" to="alert(1)" />
  </rect>
</svg>
```
**Expected:** Drop animate element.

**Safe animation**
```html
<svg>
  <circle cx="0" cy="50" r="40">
    <animate attributeName="cx" from="0" to="100" dur="1s"/>
  </circle>
</svg>
```
**Expected:** Keep animate (animating safe attribute).

**Set element**
```html
<svg>
  <rect>
    <set attributeName="href" to="javascript:alert(1)" />
  </rect>
</svg>
```
**Expected:** Drop set element.

### SVG Tiny

**Handler element**
```html
<svg>
  <handler>alert(1)</handler>
</svg>
```
**Expected:** Drop handler subtree.

**Listener element**
```html
<svg>
  <listener handler="alert(1)"/>
</svg>
```
**Expected:** Drop listener subtree.

### foreignObject

**HTML inside foreignObject**
```html
<svg>
  <foreignObject>
    <script>alert(1)</script>
  </foreignObject>
</svg>
```
**Expected:** Keep foreignObject, sanitize children (drop script).

## MathML Vectors

**JavaScript href**
```html
<math>
  <mi href="javascript:alert(1)">x</mi>
</math>
```
**Expected:** Strip href, keep mi.

**annotation-xml with HTML**
```html
<math>
  <semantics>
    <annotation-xml encoding="text/html">
      <script>alert(1)</script>
    </annotation-xml>
  </semantics>
</math>
```
**Expected:** Keep annotation-xml, sanitize children (drop script).

## Edge Cases

### Entity-encoded Content

**Encoded script text (should stay text)**
```html
<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>
```
**Expected:** Pass through unchanged (literal text, not a tag).

### Noscript

**Content inside noscript**
```html
<noscript>
  <p>JavaScript is disabled</p>
  <script>alert(1)</script>
</noscript>
```
**Expected:** Keep noscript, sanitize children (strip on* attrs, drop script).

### Malformed Markup

**Unclosed tags**
```html
<script>alert(1)
<p>Text
```
**Expected:** Handle gracefully (parser tolerates this).

**Self-closing on non-void**
```html
<script/>
```
**Expected:** Treat as `<script>` and drop subtree.

### Comments

**Comment with script-like text**
```html
<!-- <script>alert(1)</script> -->
```
**Expected:** Keep comment unchanged.

### vbscript:

**VBScript URL (IE legacy)**
```html
<a href="vbscript:msgbox(1)">Click</a>
```
**Expected:** Strip href (treat like javascript:).
