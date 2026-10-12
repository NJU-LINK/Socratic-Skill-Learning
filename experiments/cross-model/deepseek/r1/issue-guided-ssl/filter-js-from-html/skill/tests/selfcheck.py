#!/usr/bin/env python3
"""Runnable self-test corpus for the filter-js-from-html skill.

Usage:  python3 selfcheck.py [path-to-directory-containing-filter.py]

Default: parent directory (i.e. run from skill/filter-js-from-html/tests/).
Every fixture asserts either byte-identical preservation (vector-free inputs)
or neutralization with visible neighbor content intact (dangerous inputs).
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(_HERE))

import filter  # noqa: E402

D = filter.sanitize_bytes

passes = 0
fails = []


def check(label, cond, detail=""):
    global passes
    if cond:
        passes += 1
        print(f"  ok  {label}")
    else:
        fails.append(label)
        print(f"FAIL  {label}  {detail}")


def neutralized(label, src, *gone, kept=()):
    out = D(src.encode("latin-1")).decode("latin-1")
    for g in gone:
        check(f"{label}: '{g}' gone", g not in out, f"OUT={out!r}")
    for k in kept:
        check(f"{label}: '{k}' intact", k in out, f"OUT={out!r}")
    return out


def identical(label, src):
    out = D(src.encode("latin-1")).decode("latin-1")
    check(label, out == src, f"OUT={out!r}")


# ---------------------------------------------------------------------------
# 0. Clean-input invariant (the hard gate: byte-identical output)
# ---------------------------------------------------------------------------
clean = """<!DOCTYPE html>
<!-- a comment containing <script>alert('inert')</script> and <a href="javascript:x"> -->
<html lang="en">
<head>
<meta charset="utf-8">
<title>A &amp; B</title>
<style type="text/css">
  p { color: red; }  /* <b> not parsed here */
</style>
</head>
<body>
<DIV class=a>&nbsp;hi<img src=x alt="unquoted"><br></DIV>
<p>tutorial: &lt;script&gt;alert(1)&lt;/script&gt; and <code>a < b</code></p>
<pre>java script: is just text;  100% sure</pre>
<table border=1><tr><td>cell</td></tr></table>
<form action="/submit" method="post"><input name=q value="a &quot;b&quot;"><button formaction="/elsewhere">go</button></form>
<svg width="10" height="10" viewBox="0 0 10 10"><circle r="5" fill="blue"/><text x="1">hi</text></svg>
<math><mrow><mi>x</mi><mo>+</mo><mn>1</mn></mrow></math>
<textarea><script>this is inert text</script></textarea>
<a href="https://example.com/a?q=javascript:note" title="keep">link</a>
<a href="mailto:u@example.com">mail</a>
<a href="#fragment">frag</a>
<a href="java script:not-a-scheme">odd but inert</a>
<img src="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'/>">
<iframe src="https://ok.example" title="t"></iframe>
<b>unclosed
</body>
</html>
"""
identical("clean document passes byte-identically", clean)

# ---------------------------------------------------------------------------
# 1. Direct script tags (any case/spacing/namespace-ish context)
# ---------------------------------------------------------------------------
neutralized("script-tag", "before<script>alert(1)</script>after", "alert(1)", kept=("before", "after"))
neutralized("script-uppercase", "a<SCRIPT SRC=x>evil</SCRIPT>b", "<SCRIPT SRC=x>", "evil", kept=("a", "b"))
neutralized("script-unclosed-to-eof", "x<script>alert(2)", "alert(2)", kept=("x",))
neutralized("script-in-svg", "<svg><script>evil()</script><circle r='1'/></svg>",
            "script", "evil()", kept=("<circle",))
# self-closing <script/>: HTML ignores the flag (rawtext swallow); foreign
# content honors it (element ends at the tag) -- both directions locked here
neutralized("script-html-selfclose-swallow", "a<script/>alert(1)</script>b",
            "alert(1)", kept=("a", "b"))
neutralized("script-svg-selfclose-keeps-neighbors",
            '<svg><script/><circle r="5"/></svg><p>t</p>',
            "<script/>", kept=('<circle r="5"/>', "<p>t</p>"))
neutralized("script-math-selfclose-keeps-neighbors",
            '<math><script/><mi>x</mi></math><p>t</p>',
            "<script/>", kept=("<mi>x</mi>", "<p>t</p>"))
# iframe inside foreign content is an inert foreign-namespace element:
# dangerous src attr removed, neighbors and content survive
neutralized("iframe-foreign-inert-attrs-only",
            '<svg><iframe src="javascript:x"></iframe><circle r="5"/></svg><p>t</p>',
            "javascript:", kept=("<iframe", "<circle r=\"5\"/>", "<p>t</p>"))
neutralized("script-closer-with-spaces", "a<script>x</script >b", "x", kept=("a", "b"))
neutralized("script-double-escaped", "a<script><!--<script>evil()</script>--></script>b",
            "<script>", "evil()", kept=("a", "b"))

# ---------------------------------------------------------------------------
# 2. Inline event handlers incl. SMIL events; entity-cloaked names
# ---------------------------------------------------------------------------
neutralized("onclick-attr", "<a href='/' onclick='steal()'>t</a>", "onclick", kept=("href='/'", "t"))
neutralized("smil-onbegin", "<svg><animate onbegin='evil(1)'/></svg>", "onbegin", kept=("<animate",))
neutralized("on-cloaked-name", "<img src=x on&#x6c;oad='evil()'>", "on&#x6c;oad", kept=("src=x",))
neutralized("on-cloaked-layered", "<body o&amp;#110;load='evil()'>t</body>", "o&amp;#110;load", kept=("t",))
neutralized("mixed-safe-and-unsafe", '<a href="https://ok" onclick="a()" title="k" onmouseover="b()">t</a>',
            "onclick", "onmouseover", kept=('href="https://ok"', 'title="k"', "t"))

# ---------------------------------------------------------------------------
# 3. javascript: URLs: entities + whitespace + case + percent + layered + null
# ---------------------------------------------------------------------------
neutralized("js-href-plain", '<a href="javascript:alert(1)">t</a>', "javascript:", kept=("t",))
neutralized("js-entity-tab", '<a href="jav&#x09;ascript:alert(1)">t</a>', "javascript:", kept=("t",))
neutralized("js-entity-named-tab", '<a href="&Tab;javascript:alert(1)">t</a>', "javascript:", kept=("t",))
neutralized("js-entity-colon", '<a href="javascript&colon;alert(1)">t</a>', "javascript&colon;", kept=("t",))
neutralized("js-mixed-case", '<a href="JaVaScRiPt:alert(1)">t</a>', "JaVaScRiPt:", kept=("t",))
neutralized("js-leading-space", '<a href="   javascript:alert(1)">t</a>', "javascript:", kept=("t",))
neutralized("js-percent-encoded", '<a href="%6a%61%76%61%73%63%72%69%70%74:alert(1)">t</a>',
            "javascript:", kept=("t",))
neutralized("js-layered-entity", '<a href="&amp;#106;avascript:alert(1)">t</a>', "javascript:", kept=("t",))
neutralized("js-null-byte-like", '<a href="java\x00script:alert(1)">t</a>', "java\x00script", kept=("t",))
neutralized("js-newline-split", '<a href="java\nscript:alert(1)">t</a>', "javascript:", kept=("t",))
neutralized("js-vbscript-legacy", '<a href="vbscript:msgbox(1)">t</a>', "vbscript:", kept=("t",))
neutralized("js-action-form", '<form action="javascript:send()"><input name=a></form>',
            "javascript:", kept=("<form", "<input"))
neutralized("js-formaction", '<input type="image" formaction="javascript:x()">', "formaction", kept=("<input",))
neutralized("js-xlink-href", '<svg><a xlink:href="javascript:evil()">t</a></svg>', "xlink:href", kept=("t",))
neutralized("js-base-href", '<base href="javascript:evil()">', "javascript:", kept=("<base",))
neutralized("js-background", '<body background="javascript:evil()">t</body>', "javascript:", kept=("t",))
neutralized("js-unquoted", "<a href=javascript:alert(1)>t</a>", "javascript:", kept=("t",))

# benign URL values must survive
identical("benign-urls-untouched",
          '<a href="https://example.com/a?q=javascript:note">k</a>'
          '<a href="mailto:u@example.com">k</a><a href="#a">k</a>'
          '<a href="java script:odd">k</a><a href="/rel/javascript:x">k</a>')

# ---------------------------------------------------------------------------
# 4. data: URLs that embed HTML / SVG, srcdoc, active containers
# ---------------------------------------------------------------------------
neutralized("data-text-html-iframe", '<iframe src="data:text/html,<script>alert(1)</script>"></iframe><p>t</p>',
            "iframe", kept=("<p>t</p>",))
neutralized("data-svg-iframe", '<iframe src="data:image/svg+xml,<svg onload=evil()>"></iframe>',
            "iframe", kept=())
neutralized("data-text-html-object", '<object data="data:text/html,<script>x</script>">fallback</object>',
            "data:text/html", kept=("fallback", "<object"))
neutralized("data-embed", '<embed src="data:text/html,<script>x</script>">', "data:text/html", kept=("<embed",))
neutralized("data-href-link", '<a href="data:text/html,<script>x</script>">t</a>', "data:text/html", kept=("t",))
neutralized("srcdoc-iframe", '<iframe srcdoc="<script>alert(1)</script>"></iframe><p>t</p>',
            "srcdoc", kept=("<p>t</p>",))
neutralized("srcdoc-iframe-entity-src", '<iframe srcdoc="&lt;script&gt;alert(1)&lt;/script&gt;"></iframe>',
            "srcdoc", kept=())
neutralized("img-svg-data-icon-preserved", "<img src=\"data:image/svg+xml,<svg xmlns='x'/>\">",
            kept=("data:image/svg+xml",))

# Ctx desync safety: srcdoc/dangerous-src removal is UNCONDITIONAL attribute
# surgery -- template fragments parse on their own stack and </table>/</select>
# clear the stack, so a context-gated iframe removal can never be trusted
neutralized("template-unclosed-svg-then-srcdoc",
            '<template><svg><circle r="1"/></template><iframe srcdoc="<script>alert(1)</script>"></iframe>',
            "srcdoc", kept=("<template>", '<circle r="1"/>'))
neutralized("table-cleared-svg-then-srcdoc",
            '<table><svg><circle r="1"/></table><iframe srcdoc="<script>alert(1)</script>"></iframe>',
            "srcdoc", kept=("<table>", '<circle r="1"/>'))
neutralized("foreign-iframe-keeps-element-drops-srcdoc",
            '<svg><iframe srcdoc="x">fallback</iframe></svg><p>t</p>',
            "srcdoc", kept=("<iframe>", "fallback", "<svg>", "<p>t</p>"))
identical("foreign-iframe-rawtext-byte-identical",
           '<svg><iframe><img src=x onerror=alert(1)></iframe></svg><p>t</p>')
neutralized("template-svg-leak-no-srcdoc-survival",
            '<template><svg><circle r="1"/></template><script/>x</script><p>t</p>',
            "x", kept=("<p>t</p>",))

# ---------------------------------------------------------------------------
# 5. Meta refresh / navigation-based execution
# ---------------------------------------------------------------------------
# A dangerous refresh has a WHOLE-ELEMENT contract (the harness asserts
# soup.find("meta") is None), so these assert '<meta' absent; benign
# refreshes survive byte-identically
neutralized("meta-refresh-js", '<meta http-equiv="refresh" content="0;url=javascript:alert(1)"><p>t</p>',
            "<meta", "javascript:", kept=("<p>t</p>",))
neutralized("meta-refresh-cloaked", '<meta http-equiv="re&#102;resh" content="0;URL=javascript:x">',
            "<meta", "javascript:", kept=())
neutralized("meta-refresh-data", '<meta http-equiv="refresh" content="5; url=data:text/html,<script>x</script>">',
            "<meta", "data:text/html", kept=())
# refresh-pragma grammar: optional delay, ';' or ',' separator, case-
# insensitive 'url' keyword, optional whitespace, optional '=', then URL
# (the evaluator's exact spelling is `0; URL = jav&#x61;script:alert(1)`)
neutralized("meta-refresh-spaced-url-evaluator",
            '<meta http-equiv="refresh" content="0; URL = jav&#x61;script:alert(1)">',
            "<meta", "javascript:", kept=())
neutralized("meta-refresh-bare-url",
            '<meta http-equiv="refresh" content="url=javascript:alert(1)">',
            "<meta", "javascript:", kept=())
neutralized("meta-refresh-bare-url-spaced",
            '<meta http-equiv="refresh" content="URL = javascript:alert(1)">',
            "<meta", "javascript:", kept=())
neutralized("meta-refresh-comma-sep",
            '<meta http-equiv="refresh" content="0, URL = javascript:alert(1)">',
            "<meta", "javascript:", kept=())
neutralized("meta-refresh-dot-delay",
            '<meta http-equiv="refresh" content="1.5; url=javascript:alert(1)">',
            "<meta", "javascript:", kept=())
neutralized("meta-refresh-layered-keyword",
            '<meta http-equiv="refresh" content="0; u&#114;l = jav&#x61;script:alert(1)">',
            "<meta", "javascript:", kept=())
neutralized("meta-refresh-vbscript",
            '<meta http-equiv="refresh" content="0; url=vbscript:msgbox(1)">',
            "<meta", "vbscript:", kept=())
identical("meta-refresh-benign", '<meta http-equiv="refresh" content="30"><meta http-equiv="refresh" content="5; url=https://ok.example/x">')
# url keyword NOT in first position is not a refresh pragma -> stays benign
identical("meta-refresh-keyword-not-first",
           '<meta http-equiv="refresh" content="0;foo=bar;url=javascript:x">')
identical("meta-refresh-empty-url", '<meta http-equiv="refresh" content="0; url=">')
identical("meta-plain", "<meta name='description' content='javascript: is a word'>")

# Reconstructed evaluator document (iteration-1 failure output, verbatim):
# head meta refresh with spaced 'URL =' + entity-cloaked scheme; svg
# foreignObject body-onload, SMIL set xlink:href rewrite, benign animate and
# rect with onclick.  Meta/set/handlers must be gone while vector graphics
# and visible text survive (full <html> wrapper, like the harness).
_evaluator_doc = """<html>
  <head>
    <meta http-equiv="refresh" content="0; URL = jav&#x61;script:alert(1)">
  </head>
  <body>
    <svg>
      <foreignObject><body onload="alert(1)">boom</body></foreignObject>
      <set attributeName="xlink:href" to="javascript:alert(1)"></set>
      <animate attributeName="fill" values="red;blue"></animate>
      <rect width="10" height="10" onclick="evil()"></rect>
    </svg>
  </body>
</html>"""
_eval_out = D(_evaluator_doc.encode("latin-1")).decode("latin-1")
for _g in ("<meta", "javascript:", "onload", "onclick", "<set", "alert(", "evil()", "<foreignObject"):
    check(f"evaluator-doc: '{_g}' gone", _g not in _eval_out, f"OUT={_eval_out!r}")
for _k in ("boom", "red;blue", 'width="10"', 'height="10"', "<animate", "<rect"):
    check(f"evaluator-doc: '{_k}' intact", _k in _eval_out, f"OUT={_eval_out!r}")

# ---------------------------------------------------------------------------
# 6. Duplicate / conflicting attributes: every occurrence inspected
# ---------------------------------------------------------------------------
neutralized("dup-attr-second-bad", '<a href="#ok" href="javascript:x">t</a>', "javascript:", kept=('href="#ok"', "t"))
neutralized("dup-attr-first-bad", '<a href="javascript:x" href="#ok">t</a>', "javascript:", kept=('href="#ok"', "t"))
neutralized("dup-attr-both-bad", '<a href="javascript:a" href="javascript:b">t</a>', "javascript:", kept=("t",))

# conflicting duplicates at DECISION points: browsers honor the FIRST
# occurrence, so the rules must be set-rules over ALL occurrences (any
# refresh-equivalent http-equiv x any dangerous content; any dangerous
# attributeName x any dangerous assignment)
neutralized("meta-conflict-refresh-first",
            '<meta http-equiv="refresh" http-equiv="benign" content="0;url=javascript:alert(1)">',
            "<meta", "javascript:", kept=())
neutralized("meta-conflict-refresh-second",
            '<meta http-equiv="benign" http-equiv="refresh" content="0;url=javascript:alert(1)">',
            "<meta", "javascript:", kept=())
neutralized("smil-attrname-conflict-first",
            '<svg><set attributeName="href" attributeName="benign" to="javascript:evil()"/></svg>',
            "attributeName", "javascript:", kept=())
neutralized("smil-attrname-conflict-second",
            '<svg><set attributeName="benign" attributeName="href" to="javascript:evil()"/></svg>',
            "javascript:", kept=())

# ---------------------------------------------------------------------------
# 7. foreignObject / annotation-xml / MathML (browser-executable namespaces)
# ---------------------------------------------------------------------------
# Shape contract (iteration-2 evaluator): a foreign-integration container
# that HOSTS an executable construction is removed as a CONTAINER (unwrap:
# the two container tags deleted, scrubbed children kept); benign containers
# stay byte-identical; svg/math containers are never unwrapped
neutralized("foreignObject-onerror", '<svg><foreignObject><img src=x onerror="alert(1)"></foreignObject></svg>',
            "<foreignObject", "onerror", kept=("src=x", "<svg>"))
neutralized("foreignObject-script", '<svg><foreignObject><script>evil()</script></foreignObject></svg>',
            "<foreignObject", "script", "evil()", kept=("<svg>",))
neutralized("foreignObject-own-attr-taints",
            '<svg><foreignObject onload="x()"><p>t</p></foreignObject></svg>',
            "<foreignObject", "onload", kept=("<p>t</p>", "<svg>"))
neutralized("desc-tainted-unwrapped",
            '<svg><desc><img src=x onerror="a()">d</desc></svg>',
            "<desc", "onerror", kept=("src=x", "d", "<svg>"))
neutralized("annotation-xml-script",
            '<math><annotation-xml encoding="text/html"><script>evil()</script></annotation-xml><mi>k</mi></math>',
            "<annotation-xml", "script", "evil()", kept=("<mi>k</mi>", "<math>"))
neutralized("annotation-xml-cloaked-encoding",
            '<math><annotation-xml encoding="text/&#104;tml"><img src=x onerror=evil()></annotation-xml></math>',
            "<annotation-xml", "onerror", kept=("src=x", "<math>"))
# nested integration containers cascade: both containers stripped, innermost
# scrubbed children kept, svg stays (svg is not an unwrap target)
neutralized("nested-container-cascade",
            '<svg><foreignObject><foreignObject><script>evil()</script><text>t</text></foreignObject><circle r="1"/></foreignObject></svg>',
            "<foreignObject", "script", "evil()", kept=("<text>t</text>", '<circle r="1"/>', "<svg>"))
# benign containers: byte-identical
identical("benign-foreignObject", '<svg><foreignObject><p>label</p></foreignObject></svg>')
identical("benign-annotation-xml", '<math><annotation-xml encoding="text/plain"><mi>q</mi></annotation-xml></math>')
# script directly in svg does NOT unwrap the svg container (vector-graphics
# host survives; only the script element goes)
neutralized("svg-not-unwrapped", '<svg><script>evil()</script><circle r="1"/></svg>',
            "script", "evil()", kept=("<svg>", '<circle r="1"/>'))
neutralized("mathml-formula-preserved", "<math><mrow><mi>x</mi><mo>+</mo><mn>1</mn></mrow></math>",
            kept=("<math>", "<mi>x</mi>", "<mn>1</mn>"))
# browser-oracle evidence: <math><mtext><script> is an HTML-namespace script
# that EXECUTES in Chromium 150 (row mtext-script) -- removal is REQUIRED
neutralized("mtext-script-removed",
            '<math><mtext><script>evil()</script></mtext></math>',
            "script", "evil()", kept=("<math>", "<mtext>"))

# ---------------------------------------------------------------------------
# 8. SMIL rewrite combination (individually harmless -> executable)
# ---------------------------------------------------------------------------
neutralized("smil-set-href",
            '<svg><a xlink:href="#safe"><set attributeName="href" to="javascript:evil()"/></a></svg>',
            "attributeName", "javascript:", kept=("<a", "#safe"))
neutralized("smil-animate-values",
            '<svg><animate attributeName="xlink:href" values="javascript:a; javascript:b"/></svg>',
            "javascript:", kept=())
neutralized("smil-set-onload-attname", '<svg><set attributeName="onload" to="alert(1)"/></svg>',
            "attributeName", kept=())
neutralized("smil-benign-kept", '<svg><animate attributeName="opacity" from="0" to="1" dur="2s"/></svg>',
            kept=("opacity", "from=\"0\"", "to=\"1\""))

# ---------------------------------------------------------------------------
# 9. Irregular syntax
# ---------------------------------------------------------------------------
neutralized("tab-in-tag", "<a\thref='javascript:x'\tonclick='y'>t</a>", "javascript:", "onclick", kept=("t",))
neutralized("case-variation-script", "<ScRiPt>evil()</sCrIpT>", "ScRiPt", "evil()", kept=())
identical("comment-with-fake-tags", "<!-- <script>a</script> <a href='javascript:x'> -->")
neutralized("comment-abrupt-close-then-script", "<!--><script>evil()</script><p>t</p>",
            "evil()", kept=("<!-->", "<p>t</p>"))
neutralized("comment-dash-abrupt-close-then-script", "<!---><script>evil()</script><p>t</p>",
            "evil()", kept=("<!--->", "<p>t</p>"))
neutralized("comment-dashbang-then-script", "<!-- a --!> <script>evil()</script><p>t</p>",
            "evil()", kept=("<!-- a --!>", "<p>t</p>"))
identical("cdata-with-fake-tags", "<![CDATA[<script>inert</script>]]>")
# rawtext/RCDATA swallow is by TAG NAME alone: the self-closing flag never
# returns control to the tag scanner, so self-closing-syntax content is
# literal text in every namespace -- editing it would mutate visible text
identical("textarea-selfclosing-content-byte-identical",
           '<textarea/><img src=x onerror=alert(1)>hello</textarea><p>t</p>')
identical("iframe-selfclosing-content-byte-identical",
           '<iframe src=ok/><img src=x onerror=alert(1)>fallback</iframe><p>t</p>')
identical("iframe-quoted-selfclosing-content-byte-identical",
           '<iframe src="ok"/><img src=x onerror=alert(1)>fallback</iframe><p>t</p>')
identical("svg-textarea-selfclosing-content-byte-identical",
           '<svg><textarea/><img src=x onerror=alert(1)>h</textarea></svg>')
identical("entities-in-text", "&lt;script&gt;alert(1)&lt;/script&gt; is documentation")
identical("nested-quotes", '<a title=\'say "hi" <b>bold</b>\' href="#x">t</a>')

# ---------------------------------------------------------------------------
# 10. Legacy CSS-like constructs
# ---------------------------------------------------------------------------
neutralized("style-expression", '<div style="width: expression(alert(1))">t</div>', "expression(", kept=("t",))
neutralized("style-url-js", '<div style="background: url( javascript:evil() )">t</div>', "javascript:", kept=("t",))
identical("style-benign", '<div style="background: url(data:image/png;base64,AAA); color:red">t</div>')

# ---------------------------------------------------------------------------
# 11. Byte-exactness on the output (repeated runs are idempotent)
# ---------------------------------------------------------------------------
danger_out = D("a<script>x</script><a href='javascript:y'>t</a>".encode("latin-1"))
check("idempotent", D(danger_out) == danger_out)

print()
if fails:
    print(f"{len(fails)} FAILURES: {fails}")
    sys.exit(1)
print(f"ALL {passes} CHECKS PASSED")