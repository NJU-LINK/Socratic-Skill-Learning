#!/usr/bin/env python3
"""make_corpus.py -- regenerate the validation corpus for filter-js-from-html.

Builds:
  tests/in/   - static corpus (alert(N) payloads), all four spec axes
                (vectors, preservation, parsing irregularity, obfuscation)
                + iteration-2/3 additions (frameset fragments, deep nesting,
                deep srcdoc chains, style/meta semantics, oracle control)
  tests/out/  - filtered versions (run filter.py on each copy)
  bcorpus/    - browser corpus (alert(N) rewritten to window.__xss=N) plus
                x.filtered.html twins for assets/deep_check.py

Fixture discipline: the ORIGINAL is written first, then copied to the
.filtered.html twin, and the filter runs on the COPY.  The original is never
mutated while building pairs (a mutated original would trivially read as
INERT in the browser harness).  A `zzz_control.html` oracle pair (plain
<script>__xss=1</script>) is always included so deep_check.py can abort when
the harness itself is broken.

Usage: python3 make_corpus.py   (requires /app/filter.py)
"""
import os, re, base64, subprocess, shutil, glob


def build_deep_srcdoc(n):
    """n nested <iframe srcdoc=...> wrappers with an executable anchor at
    the leaf.  Both '&' and '"' are entity-escaped at every level so each
    parse round-trips the structure cleanly (real deep srcdoc recursion;
    browsers execute the leaf javascript: anchor -- verified)."""
    s = '<a href="javascript:alert(1)">x</a>'
    for _ in range(n):
        s = '<iframe srcdoc="' + s.replace('&', '&amp;').replace('"', '&quot;') + '"></iframe>'
    return s


C = {
'01_script_tag.html': '<!DOCTYPE html><html><head><title>t</title></head><body>\n<script>alert(1)</script>\n<script src="https://evil.com/x.js"></script>\n<ScRiPt type="text/javascript">alert(2)</ScRiPt>\n<p>hello world</p>\n</body></html>',
'02_event_handlers.html': '<html><body>\n<img src="x.png" onerror="alert(1)" width=10 height=20 alt="pic">\n<a href="page.html" onclick="steal()" title="link">go</a>\n<div onmouseover="evil()">hover</div>\n<input type="text" onfocus="evil()" value="v">\n</body></html>',
'03_javascript_urls.html': '<html><body>\n<a href="javascript:alert(1)">click</a>\n<a href="JaVaScRiPt:alert(2)">click2</a>\n<a href="page2.html">safe</a>\n<img src="javascript:evil()">\n<form action="javascript:alert(3)"><input type="submit"></form>\n<button formaction="javascript:alert(4)">btn</button>\n<input type="submit" formaction="javascript:alert(5)" value="go">\n</body></html>',
'04_active_containers.html': '<html><body>\n<iframe src="data:text/html,<script>alert(1)</script>"></iframe>\n<iframe srcdoc="<script>alert(2)</script><p>frame body</p>"></iframe>\n<iframe src="https://example.com/ok"></iframe>\n<object data="data:text/html;base64,PHNjcmlwdD5hbGVydCgzKTwvc2NyaXB0Pg=="></object>\n<object data="movie.swf"></object>\n<embed src="data:text/html,<script>alert(4)</script>">\n<embed src="clip.mp4">\n<frame src="javascript:alert(5)">\n</body></html>',
'05_svg.html': '<!DOCTYPE html>\n<html><body>\n<svg width="100" height="100" onload="alert(1)">\n  <circle cx="50" cy="50" r="40" fill="red"/>\n  <script>alert(2)</script>\n  <a xlink:href="javascript:alert(3)"><text x="10" y="20">link</text></a>\n  <a href="javascript:alert(4)"><text x="10" y="40">link2</text></a>\n  <a href="https://safe.example/x"><text x="10" y="60">safe link</text></a>\n  <image href="data:image/png;base64,iVBORw0KGgo=" x="0" y="0"/>\n  <set attributeName="onload" to="alert(5)"/>\n  <animate attributeName="href" values="javascript:alert(6)" dur="1s"/>\n  <animate attributeName="x" values="0;10" dur="1s"/>\n</svg>\n</body></html>',
'06_mathml.html': '<!DOCTYPE html>\n<html><body>\n<math display="block">\n  <mrow><mi>x</mi><mo>=</mo><mfrac><mn>1</mn><mn>2</mn></mfrac></mrow>\n  <script>alert(1)</script>\n  <maction actiontype="statusline"><mtext>hover</mtext></maction>\n</math>\n<p>equation above</p>\n</body></html>',
'07_meta_refresh.html': '<!DOCTYPE html>\n<html><head>\n<meta charset="utf-8">\n<meta http-equiv="refresh" content="0; url=javascript:alert(1)">\n<meta http-equiv="refresh" content="5;url=https://example.com/next">\n<title>t</title>\n</head><body><p>x</p></body></html>',
'08_style.html': '<!DOCTYPE html>\n<html><head><style>\nbody { color: red; }\na:hover { background: url(javascript:alert(1)); }\ndiv { width: expression(alert(2)); }\np { margin: 0; }\n</style></head>\n<body>\n<div style="background:url(javascript:alert(3)); color:blue">x</div>\n<div style="background-image: url(\'https://ok.example/i.png\'); height: expression(alert(4))">y</div>\n<p style="color: green">z</p>\n</body></html>',
'10_preserve.html': '<!DOCTYPE html>\n<html><head><title>Preserve me</title></head>\n<body>\n<h1>Heading</h1>\n<table border="1"><thead><tr><th>Col A</th><th>Col B</th></tr></thead>\n<tbody><tr><td>r1c1</td><td>r1c2</td></tr><tr><td>r2c1</td><td>r2c2</td></tr></tbody></table>\n<form action="/submit" method="post">\n  <label>Name: <input type="text" name="n" value="x"></label>\n  <select name="s"><option value="1">one</option><option value="2">two</option></select>\n  <textarea name="t">some text</textarea>\n  <button type="submit">Send</button>\n</form>\n<ul><li>item 1<ul><li>nested</li></ul></li><li>item 2</li></ul>\n<p>Text with <em>emphasis</em>, <strong>bold</strong>, <a href="/rel">relative link</a>,\n<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==" alt="dot">,\n&amp; &lt; &gt; &quot; entities, unicode: café ☃ 日本語.</p>\n<blockquote cite="https://example.com/q">quote</blockquote>\n<dl><dt>term</dt><dd>def</dd></dl>\n<pre>  code with   spacing</pre>\n<hr>\n</body></html>',
'11_mixed_attrs.html': '<html><body>\n<a href="bad.html" onclick="evil()" data-role="nav" aria-label="Go" title="t" id="l1">mixed</a>\n<img src="safe.png" onerror="evil()" onload="evil2()" width="5" height="5" data-id="img1">\n<div class="a b" id="d1" onmousemove="x()" style="color:red" tabindex="0">div</div>\n</body></html>',
'12_nested_small.html': '<!DOCTYPE html>\n<html><body>\n<div><p>safe para</p><p onclick="evil()">clickable para</p><p>another safe <span>span</span></p></div>\n<table><tr><td>cell1</td><td><a href="javascript:alert(1)">cell2 link</a></td><td>cell3</td></tr></table>\n</body></html>',
'20_malformed.html': '<!DOCTYPE html>\n<html><body>\n<p>unclosed para\n<div>mis  <  nested   <span>tags</div>\n<img src="a.png" width="10" height="20">\n<p>after <b>bold <i>italic</b> mixed</i>\n<table><tr><td>misplaced</table><p>after table</p>\n</body></html>',
'21_case_spacing_tabs.html': '<HTML>\n<BODY>\n<IMG\tSRC="x.jpg"\tONERROR="alert(1)"\tWIDTH="4">\n<A\tHREF="javascript:alert(2)"\t>tab link</A>\n<DIV OnClick="evil()">case</DIV>\n<p   >weird spacing</p>\n</BODY>\n</HTML>',
'22_entities.html': '<!DOCTYPE html>\n<html><body>\n<a href="jav&#x61;script:alert(1)">entity1</a>\n<a href="&#106;avascript:alert(2)">entity2</a>\n<a href="page&#x2E;html?a=1&amp;b=2">entity3</a>\n<img src="x.png" on&#101;rror="alert(3)" alt="&quot;quoted&quot;">\n<p>&amp; &lt; &gt; &nbsp; &copy; &#65; &#x41;</p>\n</body></html>',
'23_template.html': '<!DOCTYPE html>\n<html><body>\n<template id="tpl">\n  <div class="card"><h3>Title</h3><p>body <b>bold</b></p></div>\n  <script>setup()</script>\n</template>\n<template id="tpl2"><span onclick="evil()">click</span></template>\n<p>page</p>\n</body></html>',
'24_duplicate_attrs.html': '<html><body>\n<img src="ok.png" onerror="alert(1)" onerror="alert(2)">\n<a href="safe.html" href="javascript:alert(3)">dup</a>\n<div id="a" class="x" id="b">dup id</div>\n</body></html>',
'25_noscript.html': '<!DOCTYPE html>\n<html><body>\n<noscript><p>Enable JS please</p></noscript>\n<noscript><p title="</noscript><img src=x onerror=alert(1)>">bad</noscript>\n<p>after</p>\n</body></html>',
'26_mxss_math.html': '<!DOCTYPE html>\n<html><body>\n<math><mtext></table><mglyph><style><!--</style><img title="--><img src=1 onerror=alert(1)>"></math>\n<p>after</p>\n</body></html>',
'27_broken_nesting.html': '<html><body>\n<ul><li>one<li>two<li>three</ul>\n<b><i>bold italic</b> tail</i>\n<div><p>a<p>b<p>c</div>\n<table><tr><td>1<td>2<tr><td>3</table>\n</body></html>',
'28_fragment.html': '<b>bold fragment</b><script>alert(1)</script><i>italic</i>',
'30_percent.html': '<!DOCTYPE html>\n<html><body>\n<a href="java%73cript:alert(1)">pct1</a>\n<a href="%6A%61%76%61%73%63%72%69%70%74:alert(2)">pct2</a>\n<a href="javascript%3Aalert(3)">pct3</a>\n<a href="https%3A%2F%2Fok.example%2Fp%3Fa%3D1">pct4</a>\n<img src="x.png" onerror="%61lert(4)">\n</body></html>',
'31_null_ctrl.html': '<!DOCTYPE html>\n<html><body>\n<a href="java&#0;script:alert(1)">nul1</a>\n<a href="jav\tascript:alert(2)">tab</a>\n<a href="jav\nascript:alert(3)">nl</a>\n<a href="javascript:alert(4)">plain</a>\n</body></html>',
'32_layered.html': '<!DOCTYPE html>\n<html><body>\n<a href="%6A%61va%73cript%3Aalert%281%29">layered pct</a>\n<iframe srcdoc="<a href=&quot;javascript:alert(2)&quot;>x</a>"></iframe>\n<iframe srcdoc="&lt;script&gt;alert(3)&lt;/script&gt;p"></iframe>\n<style>p{background:url(java%73cript:alert(4))}</style>\n<div style="background:url(&quot;javascript:alert(5)&quot;)">x</div>\n</body></html>',
'33_data_urls.html': '<!DOCTYPE html>\n<html><body>\n<a href="data:text/html,<script>alert(1)</script>">d1</a>\n<a href="data:image/png;base64,iVBORw0KGgo=">d2</a>\n<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">\n<img src="data:image/svg+xml,<svg onload=alert(2)>">\n<object data="data:application/xhtml+xml,<html><script>alert(3)</script></html>"></object>\n</body></html>',
'34_fragmented.html': '<!DOCTYPE html>\n<html><body>\n<svg><a xlink:href="java&#115;cript:alert(1)"><text>frag1</text></a></svg>\n<div title="safe"><p>ok</p></div>\n<a href="javascript:aler&#116;(1)">split entity</a>\n</body></html>',
'35_srcset.html': '<!DOCTYPE html>\n<html><body>\n<img srcset="a.png 1x, b.png 2x" alt="ok">\n<img srcset="javascript:alert(1) 1x" alt="bad">\n<img srcset="data:text/html,<script>alert(2)</script> 1x" alt="bad2">\n</body></html>',
'36_long_attr.html': '<!DOCTYPE html>\n<html><body>\n<div data-config="long:value:with:colons;and;many;tokens;aaaa;bbbb;cccc;dddd;eeee;ffff;gggg;hhhh;iiii;jjjj;kkkk;llll;mmmm;nnnn;oooo;pppp;qqqq;rrrr;ssss;tttt;uuuu;vvvv;wwww;xxxx;yyyy;zzzz" class="cfg">x</div>\n<a href="https://example.com/very/long/path?with=many&params=here&more=stuff&extra=1&extra2=2&extra3=3" title="long">long link</a>\n</body></html>',
'37_ctl_01.html': '<!DOCTYPE html><html><body><a href="&#01;javascript:alert(1)">ctl1</a><meta http-equiv="refresh" content="0;url=&#01;javascript:alert(2)"><form action="&#01;javascript:alert(3)"><input type="submit"></form></body></html>',
'37_ctl_0e.html': '<!DOCTYPE html><html><body><a href="&#14;javascript:alert(1)">ctl0e</a></body></html>',
'37_ctl_1b.html': '<!DOCTYPE html><html><body><a href="&#27;javascript:alert(1)">ctl1b</a></body></html>',
'38_script_mxss.html': '<!DOCTYPE html><html><body><math><mtext></table><mglyph><style><!--</style><img title="--><script>alert(1)</script>"></math><p>after</p></body></html>',
'39_frameset_fragment.html': '<frameset cols="50%,50%"><frame src="javascript:alert(1)"><frame src="top.html"></frameset>',
'40_frameset_onload.html': '<frameset onload="alert(1)"><frame src="x.html"></frameset>',
'41_lone_frame.html': '<frame src="javascript:alert(1)">',
'42_frame_data_full.html': '<!DOCTYPE html><html><head></head><frameset><frame src="data:text/html,<script>alert(1)</script>"></frameset></html>',
'43_style_mixed.html': '<!DOCTYPE html><html><head><style>body{color:red} a{background:url(javascript:alert(1))} p{margin:0}</style></head><body><div style="background:url(javascript:alert(2));color:blue">x</div><div style="color:green">ok</div></body></html>',
'44_meta_benign.html': '<!DOCTYPE html><html><head><meta http-equiv="refresh" content="5;url=https://example.com/next"><meta http-equiv="refresh" content="0;url=javascript:alert(1)"><meta charset="utf-8"></head><body><p>x</p></body></html>',
'45_deep_nesting.html': '<!DOCTYPE html><html><body>' + '<div>' * 1500 + '<script>alert(1)</script>' + '</div>' * 1500 + '</body></html>',
'46_deep_srcdoc.html': '<html><body>' + build_deep_srcdoc(30) + '</body></html>',
'zzz_control.html': '<!DOCTYPE html><html><body><script>alert(1)</script><p>oracle control</p></body></html>',
'47_foreignobject_danger.html': '<!DOCTYPE html><html><body><svg><foreignObject><body onload="alert(1)">boom</body></foreignObject></svg></body></html>',
'48_foreignobject_benign.html': '<!DOCTYPE html><html><body><svg><foreignObject><p>caption text here</p></foreignObject></svg></body></html>',
'49_smil_danger.html': '<!DOCTYPE html><html><body><svg><set attributeName="xlink:href" to="javascript:alert(1)"></set><set attributeName="onbegin" to="alert(2)"></set><animate attributeName="fill" values="red;blue"></animate><animate attributeName="x" values="0;10" dur="1s"></animate></svg></body></html>',
'50_fo_js_link.html': '<!DOCTYPE html><html><body><svg><foreignObject><a href="javascript:alert(1)">lnk</a></foreignObject></svg></body></html>',
'51_fo_comment.html': '<!DOCTYPE html><html><body><!-- <foreignObject><body onload="alert(1)">x</body></foreignObject> --><p>ok</p></body></html>',
'52_fo_attr_closer_dq.html': '<svg><foreignObject><div title="</foreignObject>"><body onload="alert(1)">x</body></div></foreignObject></svg>',
'53_fo_attr_closer_sq.html': "<svg><foreignObject><div title='</foreignObject>'><body onload=\"alert(1)\">x</body></div></foreignObject></svg>",
'54_fo_unclosed.html': '<svg><foreignObject><body onload="alert(1)">x</body></svg>',
'55_fo_gt_in_attr.html': '<svg><foreignObject data-x="a>b"><body onload="alert(1)">x</body></foreignObject></svg>',
'56_fo_selfclose_benign.html': '<svg><foreignObject/><circle r="5"/><foreignObject><body onload="alert(1)">y</body></foreignObject></svg>',
'57_fo_comment_closer.html': '<svg><foreignObject><!-- </foreignObject> --><body onload="alert(1)">z</body></foreignObject></svg>',
'58_annotation_xml_any_enc.html': '<math><annotation-xml encoding="application/xml"><body onload="alert(1)">q</body></annotation-xml><annotation-xml><body onload="alert(1)">r</body></annotation-xml></math>',
'59_annotation_xml_benign.html': '<math><annotation-xml encoding="text/mathml"><mi>x</mi><mo>=</mo><mn>1</mn></annotation-xml><annotation-xml encoding="application/xml"><p>note</p></annotation-xml></math>',
'60_fo_title_end_closer.html': '<svg><foreignObject><div title="</foreignObject>x"><body onload="alert(1)">x</body></div></foreignObject></svg>',
}


def rewrite(text):
    """alert(N) -> window.__xss payloads; also rewrite base64-embedded alerts."""
    text = re.sub(r'alert\(\s*\d*\s*\)', lambda m: '__xss=1', text)

    def b64fix(m):
        tok = m.group(0)
        try:
            dec = base64.b64decode(tok)
        except Exception:
            return tok
        if b'alert(' not in dec:
            return tok
        dec = re.sub(rb'alert\((.*?)\)', b'__xss=\\1', dec, flags=re.S)
        return base64.b64encode(dec).decode()

    return re.sub(r'[A-Za-z0-9+/]{20,}={0,2}', b64fix, text)


def main():
    tin, bcor, tout = '/app/tests/in', '/app/bcorpus', '/app/tests/out'
    for d in (tin, bcor, tout):
        os.makedirs(d, exist_ok=True)
        for f in glob.glob(d + '/*'):
            os.remove(f)
    for n, h in C.items():
        # fixture discipline: write the original FIRST, then copy it to the
        # filtered twin, then run the filter ON THE COPY -- never mutate the
        # original while building pairs.
        open(f'{tin}/{n}', 'w').write(h)
        open(f'{bcor}/{n}', 'w').write(rewrite(h))
        shutil.copy(f'{bcor}/{n}', f'{bcor}/{n}'.replace('.html', '.filtered.html'))
        subprocess.run(['python3', '/app/filter.py',
                        f'{bcor}/{n}'.replace('.html', '.filtered.html')], check=True)
        shutil.copy(f'{tin}/{n}', f'{tout}/{n}')
        subprocess.run(['python3', '/app/filter.py', f'{tout}/{n}'], check=True)
        assert open(f'{bcor}/{n}').read() == rewrite(h), 'original was mutated!'
    print('corpus:', len(C), 'cases -> tests/in, tests/out, bcorpus(+filtered); control included')


if __name__ == '__main__':
    main()