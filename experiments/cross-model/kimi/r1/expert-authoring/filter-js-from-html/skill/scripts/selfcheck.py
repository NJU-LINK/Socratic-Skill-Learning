#!/usr/bin/env python3
"""Browser-in-the-loop self-verification for an HTML JS-filter.

Usage:  python3 selfcheck.py [path/to/filter.py]     (default: /app/filter.py)

Generates a corpus of attack files (must not execute script after filtering),
benign files (must be preserved), and parser-differential stress files; runs
the given filter on each; then loads results in headless Chromium via
selenium (falling back to BeautifulSoup structural checks when selenium or a
driver is unavailable) and reports failures.

Extend the ATTACK/BENIGN/STRESS dicts with vectors from the specific task
instance you are solving; do not trust a filter that only passes here.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

FLAG = "window.__xss=(window.__xss||[]).concat(['HIT'])"

# --------------------------------------------------------------------------
# Corpus: each attack must NOT execute (many fire on load; link/form vectors
# are exercised by synthetic clicks). Feel free to add instances.
# --------------------------------------------------------------------------
ATTACK = {
    'a01_script.html':        f'<script>{FLAG}</script>',
    'a02_script_case.html':   f'<ScRiPt>{FLAG}</sCrIpT>',
    'a03_img_onerror.html':   f'<img src=x onerror="{FLAG}">',
    'a04_svg_onload.html':    f'<svg onload="{FLAG}"></svg>',
    'a05_body_onload.html':   f'<html><body onload="{FLAG}">x</body></html>',
    'a06_a_js.html':          f'<a href="javascript:{FLAG}">c</a>',
    'a07_a_js_case.html':     f'<a href="JaVaScRiPt:{FLAG}">c</a>',
    'a08_a_js_entity.html':   f'<a href="&#106;avascript:{FLAG}">c</a>',
    'a09_a_js_tab.html':      '<a href="java\tscript:%s">c</a>' % FLAG,
    'a10_iframe_data.html':   '<iframe src="data:text/html,x"></iframe>',
    'a11_iframe_srcdoc.html': '<iframe srcdoc="<script>parent.__xss=1</script>"></iframe>',
    'a12_object_data.html':   '<object data="data:text/html,x"></object>',
    'a13_embed.html':         '<embed src="data:text/html,x">',
    'a14_meta_refresh.html':  '<meta http-equiv="refresh" content="0;url=https://example.invalid/">',
    'a15_form_js.html':       f'<form action="javascript:{FLAG}"><input type="submit" value="g"></form>',
    'a16_formaction.html':    f'<form id="f"></form><button form="f" formaction="javascript:{FLAG}">g</button>',
    'a17_svg_a_xlink.html':   f'<svg><a xlink:href="javascript:{FLAG}"><text x="5" y="20">c</text></a></svg>',
    'a18_svg_smil.html':      f'<svg><a><animate attributeName="xlink:href" values="javascript:{FLAG}"/><text x="5" y="20">c</text></a></svg>',
    'a19_svg_use.html':       '<svg><use xlink:href="data:image/svg+xml;base64,PHN2Zy8+#x"/></svg>',
    'a20_math_href.html':     f'<math href="javascript:{FLAG}"><mi>x</mi></math>',
    'a21_autofocus.html':     f'<input autofocus onfocus="{FLAG}">',
    'a22_ontoggle.html':      f'<details open ontoggle="{FLAG}"><summary>s</summary></details>',
    'a23_srcset_js.html':     f'<img srcset="javascript:{FLAG} 1x">',
    'a24_style_js.html':      f'<div style="background:url(javascript:{FLAG})">x</div>',
    'a25_svg_script.html':    f'<svg><script>{FLAG}</script></svg>',
    'a26_annotation_xml.html': f'<math><annotation-xml encoding="text/html"><script>{FLAG}</script></annotation-xml></math>',
    'a27_table_script.html':  f'<table><script>{FLAG}</script><tr><td>c</td></tr></table>',
    'a28_a_data_html.html':   '<a href="data:text/html;base64,PHNjcmlwdD4hPC9zY3JpcHQ+">c</a>',
    'a29_missing_space.html': '<img src="x"onerror="%s">' % FLAG,
    'a30_unquoted.html':      '<img src=x onerror=%s>' % FLAG.replace("'", "\\'"),
    'a31_nullbyte.html':      '<a href="java\x00script:%s">c</a>' % FLAG,
    'a32_base_js.html':       f'<base href="javascript:{FLAG}//"><a href="x">c</a>',
    'a33_dup_attr.html':      '<a href="safe.html" href="javascript:%s">c</a>' % FLAG,
    'a34_foreignobject.html': f'<svg><foreignObject width="10" height="10"><img src=x onerror="{FLAG}"></foreignObject></svg>',
    'a35_leading_ws.html':    f'<a href="  \n javascript:{FLAG}">c</a>',
    'a36_style_elem.html':    f'<style>x{{background:url(javascript:{FLAG})}}</style><p>x</p>',
    'a37_script_src.html':    '<script src="https://example.invalid/x.js"></script>',
    'a38_frameset.html':      '<frameset><frame src="data:text/html,x"></frameset>',
    'a39_entity_tab.html':    f'<a href="jav&Tab;ascript:{FLAG}">c</a>',
    'a40_vbscript.html':      f'<a href="vbscript:{FLAG}">c</a>',
    'a41_pct_encoded.html':   '<a href="%6A%61%76%61%73%63%72%69%70%74%3Aalert(1)">c</a>',
    'a42_css_escape.html':    '<div style="background:url(j\\61vascript:alert(1))">x</div>',
    'a43_style_elem_esc.html': '<style>a{background:url(j\\61vascript:alert(1))}</style><p>x</p>',
}

# Benign: after filtering, body innerText must be unchanged; optional JS
# assertion (run in the browser) must hold.
BENIGN = {
    'b01_table.html':   ('<table border="1"><tr><td>cell</td></tr></table>', None),
    'b02_form.html':    ('<form action="/submit" method="post"><input name="q" required><input type="submit"></form>',
                         "document.querySelector('form').action.endsWith('/submit') && document.querySelector('input[name=q]').required"),
    'b03_link.html':    ('<a href="https://example.com/p?q=1&amp;r=2">l</a>',
                         "document.querySelector('a').href==='https://example.com/p?q=1&r=2'"),
    'b04_data_img.html': ('<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" alt="d">',
                         "document.images[0].src.startsWith('data:image/png')"),
    'b05_svg_img.html': ('<img src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=" alt="i">',
                         "document.images[0].src.startsWith('data:image/svg+xml')"),
    'b06_entities.html': ('<p>&amp; &lt; &copy; &#233; caf&eacute;</p>', None),
    'b07_svg.html':     ('<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" fill="red"/></svg>',
                         "document.querySelector('svg').getAttribute('viewBox')==='0 0 100 100'"),
    'b08_math.html':    ('<math><mi>x</mi><mo>+</mo><mn>1</mn></math>',
                         "document.querySelector('math').textContent.trim()==='x+1'"),
    'b09_attrs.html':   ('<div class="a b" id="m" data-x="1" style="color: red" role="note">s</div>',
                         "(()=>{const e=document.querySelector('#m');return e.className==='a b'&&e.dataset.x==='1'&&e.style.color==='red';})()"),
    'b10_style.html':   ('<style>p { font-weight: bold }</style><p>hi</p>',
                         "document.querySelector('style').textContent.includes('bold')"),
    'b11_meta.html':    ('<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head><body>m</body></html>',
                         "document.querySelectorAll('meta[charset],meta[name=viewport]').length===2"),
    'b12_bool.html':    ('<input type="checkbox" checked disabled>',
                         "(()=>{const i=document.querySelector('input');return i.checked&&i.disabled;})()"),
    'b13_textarea.html': ('<textarea rows="3">some <b>text</b> here</textarea>',
                         "document.querySelector('textarea').value==='some <b>text</b> here'"),
    'b14_list.html':    ('<ul><li>one<li>two</ul>', None),
    'b15_media.html':   ('<video controls src="m.mp4"><track kind="captions" src="c.vtt" default></video>',
                         "document.querySelectorAll('video,track').length===2"),
    'b16_annotation.html': ('<math><annotation-xml encoding="application/mathml+xml"><mrow><mi>n</mi></mrow></annotation-xml><mn>1</mn></math>',
                         "!!document.querySelector('annotation-xml')"),
    'b17_video_data.html': ('<video controls><source src="data:video/mp4;base64,AAAA" type="video/mp4"></video>',
                         "document.querySelector('source').src.startsWith('data:video/mp4')"),
    'b18_track_vtt.html': ('<video><track default src="data:text/vtt;base64,V0VCVlRUCg=="></video>',
                         "document.querySelector('track').src.startsWith('data:text/vtt')"),
    'b19_a_data_png.html': ('<a href="data:image/png;base64,iVBORw0KGgo=">img file</a>',
                         "document.querySelector('a').href.startsWith('data:image/png')"),
    'b20_picture_svg.html': ('<picture><source srcset="data:image/svg+xml;base64,PHN2Zy8+"><img src="x.png"></picture>',
                         "document.querySelector('source').srcset.startsWith('data:image/svg')"),
}

# Parser-differential / mXSS-style stress cases.
STRESS = {
    's01_mxss.html':        f'<form><math><mtext></form><form><mglyph><style></math><img src=x onerror="{FLAG}">',
    's02_abrupt_cmt.html':  f'<!--><img src=x onerror="{FLAG}">-->',
    's03_abrupt_cmt2.html': f'<!---><img src=x onerror="{FLAG}">-->',
    's04_plaintext.html':   f'<plaintext><script>{FLAG}</script>',
    's05_xmp.html':         f'<xmp><script>{FLAG}</script></xmp>',
    's06_noframes.html':    f'<noframes><img src=x onerror="{FLAG}"></noframes>',
    's07_noscript.html':    f'<noscript><img src=x onerror="{FLAG}"></noscript>',
    's08_noscript_break.html': '<noscript><p title="</noscript><img src=x onerror=%s>">x</p>' % FLAG.replace("'", "&#39;"),
    's09_pi.html':          f'<?xml ?><img src=x onerror="{FLAG}">',
    's10_cdata.html':       f'<![CDATA[<img src=x onerror="{FLAG}">]]>',
    's11_script_selfclose.html': '<script src="https://example.invalid/x.js"/>x</script>',
    's12_dup_rev.html':     f'<a href="javascript:{FLAG}" href="safe.html">c</a>',
    's13_select_script.html': f'<select><script>{FLAG}</script></select>',
    's14_foster.html':      f'<table><input autofocus onfocus="{FLAG}"><tr><td>x</td></tr></table>',
    's15_entity_nosemi.html': f'<a href="&#106avascript:{FLAG}">c</a>',
    's16_title_script.html': f'<html><head><title>t<script>{FLAG}</script></title></head><body>b</body></html>',
    's17_textarea_script.html': f'<textarea><script>{FLAG}</script></textarea>',
    's18_unclosed.html':    f'<img src=x onerror="{FLAG}"',
    's19_svg_set.html':     f'<svg><a><set attributeName="xlink:href" to="javascript:{FLAG}"/><text x="5" y="20">c</text></a></svg>',
    's20_deep_nest.html':   '<div>' * 100 + f'<img src=x onerror="{FLAG}">' + '</div>' * 100,
}

STRUCTURAL_JS = r'''
const bad = [];
const squash = s => s.replace(/[\x00-\x20\x7f\uFFFD]/g,'').toLowerCase();
const cssun = s => s.replace(/\\([0-9a-fA-F]{1,6})\s?/g,(m,h)=>{try{return String.fromCodePoint(parseInt(h,16))}catch(e){return ''}}).replace(/\\(.)/gs,'$1');
const urlbad = v => {
  for (const s of new Set([squash(v), squash(decodeURIComponentSafe(squash(v)))])) {
    if (/^(javascript|vbscript|livescript|mocha):/.test(s)) return true;
    if (s.startsWith('data:') && /data:[^,;]*(html|xml|svg)/.test(s)) return true;
  }
  return false;
};
function decodeURIComponentSafe(s){ try { return decodeURIComponent(s); } catch(e){ return s; } }
for (const el of document.querySelectorAll('*')) {
  const n = el.tagName.toLowerCase();
  if (['script','iframe','object','embed','applet','frame','frameset','base','foreignobject','noembed','isindex'].includes(n)) bad.push('tag:'+n);
  if (n==='annotation-xml') {
    const e=(el.getAttribute('encoding')||'').trim().toLowerCase();
    if (e==='text/html'||e==='application/xhtml+xml') bad.push('tag:annotation-xml[html]');
  }
  for (const a of el.attributes||[]) {
    const an = a.name.toLowerCase();
    if (an.startsWith('on')) bad.push('attr:'+a.name);
    if (urlbad(a.value)) bad.push('url:'+a.name);
    if (an==='style') {
      const c = squash(cssun(a.value.replace(/\/\*.*?\*\//gs,'')));
      if (['expression(','javascript:','vbscript:','-moz-binding','behavior:'].some(t=>c.includes(t))) bad.push('css:style');
    }
  }
}
for (const st of document.querySelectorAll('style')) {
  const c = squash(cssun(st.textContent.replace(/\/\*.*?\*\//gs,'')));
  if (['expression(','javascript:','vbscript:','-moz-binding','behavior:'].some(t=>c.includes(t))) bad.push('css:styleelem');
}
return bad.join(',');'''

HOOK = ("window.__xss=[];window.alert=()=>window.__xss.push('alert');"
        "window.confirm=()=>window.__xss.push('confirm');"
        "window.prompt=()=>window.__xss.push('prompt');")


def run_filter(filter_py, path):
    r = subprocess.run([sys.executable, filter_py, path],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError('filter exited %s: %s' % (r.returncode, r.stderr[-300:]))


def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    o = Options()
    o.add_argument('--headless=new')
    o.add_argument('--no-sandbox')
    o.add_argument('--disable-dev-shm-usage')
    o.add_argument('--disable-gpu')
    for binary in ('/usr/bin/chromedriver', '/usr/lib/chromium/chromedriver', None):
        try:
            d = webdriver.Chrome(service=Service(binary) if binary else Service(), options=o)
            break
        except Exception:
            continue
    else:
        raise RuntimeError('no chromedriver')
    d.set_page_load_timeout(15)
    d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
    return d


def main():
    filter_py = sys.argv[1] if len(sys.argv) > 1 else '/app/filter.py'
    tmp = tempfile.mkdtemp(prefix='filtercheck-')
    fails = []

    try:
        driver = make_driver()
    except Exception as e:
        print('!! selenium/chromium unavailable (%s); structural fallback only' % e)
        driver = None

    def write_case(name, body):
        p = os.path.join(tmp, name)
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write('<!DOCTYPE html>\n' + body)
        return p

    try:
        # ---- attack + stress: no execution, structurally clean ----
        for corpus in (ATTACK, STRESS):
            for name, body in corpus.items():
                p = write_case(name, body)
                try:
                    run_filter(filter_py, p)
                except Exception as e:
                    fails.append((name, 'FILTER-ERR %s' % e))
                    continue
                if driver is None:
                    from bs4 import BeautifulSoup
                    from urllib.parse import unquote
                    import re as _re
                    soup = BeautifulSoup(open(p, encoding='utf-8'), 'html.parser')
                    bad = []

                    def _sq(s):
                        return _re.sub(r'[\x00-\x20\x7f\ufffd]+', '', s).lower()

                    def _urlbad(v):
                        for cand in {_sq(v), _sq(unquote(_sq(v)))}:
                            if cand.startswith(('javascript:', 'vbscript:', 'livescript:', 'mocha:')):
                                return True
                            if cand.startswith('data:') and _re.search(r'data:[^,;]*(html|xml|svg)', cand):
                                return True
                        return False

                    def _cssbad(v):
                        v = _re.sub(r'/\*.*?\*/', '', v, flags=_re.S)
                        v = _re.sub(r'\\([0-9a-fA-F]{1,6})\s?',
                                    lambda m: chr(int(m.group(1), 16)) if int(m.group(1), 16) <= 0x10FFFF else '', v)
                        v = _re.sub(r'\\(.)', r'\1', v, flags=_re.S)
                        v = _sq(v)
                        return any(t in v for t in ('expression(', 'javascript:', 'vbscript:', '-moz-binding', 'behavior:'))

                    for t in soup.find_all(True):
                        if t.name in ('script', 'iframe', 'object', 'embed', 'applet', 'frame', 'frameset', 'base', 'foreignobject', 'noembed', 'isindex'):
                            bad.append('tag:' + t.name)
                        if t.name == 'annotation-xml' and (t.get('encoding') or '').strip().lower() in ('text/html', 'application/xhtml+xml'):
                            bad.append('tag:annotation-xml[html]')
                        if t.name == 'style' and t.string and _cssbad(str(t.string)):
                            bad.append('css:styleelem')
                        for a, v in t.attrs.items():
                            al = a.lower()
                            if al.startswith('on'):
                                bad.append('attr:' + a)
                            if _urlbad(str(v)):
                                bad.append('url:' + a)
                            if al == 'style' and _cssbad(str(v)):
                                bad.append('css:style')
                    if bad:
                        fails.append((name, 'DOM:' + ','.join(sorted(set(bad)))))
                    continue
                try:
                    driver.get('file://' + p)
                    time.sleep(0.9)
                    struct = driver.execute_script(STRUCTURAL_JS)
                    for el in driver.execute_script(
                            "return [...document.querySelectorAll('a,area,button,input,summary,text,select,textarea')]")[:50]:
                        try:
                            el.click()
                        except Exception:
                            pass
                        time.sleep(0.03)
                    time.sleep(0.3)
                    xss = driver.execute_script('return (window.__xss||[]).join(",")')
                    probs = []
                    if xss:
                        probs.append('EXEC:' + xss)
                    if struct:
                        probs.append('DOM:' + struct)
                    if probs:
                        fails.append((name, '; '.join(probs)))
                except Exception as e:
                    fails.append((name, 'BROWSER-ERR %s %s' % (type(e).__name__, str(e)[:140])))

        # ---- benign: unchanged text + structural assertions ----
        for name, (body, assertion) in BENIGN.items():
            p = write_case(name, body)
            try:
                orig_text = None
                if driver is not None:
                    driver.get('file://' + p)
                    time.sleep(0.2)
                    orig_text = driver.execute_script('return document.body ? document.body.innerText : ""')
                run_filter(filter_py, p)
                probs = []
                if driver is not None:
                    driver.get('file://' + p)
                    time.sleep(0.2)
                    new_text = driver.execute_script('return document.body ? document.body.innerText : ""')
                    if orig_text != new_text:
                        probs.append('TEXT %r -> %r' % (orig_text, new_text))
                    if assertion and not driver.execute_script('return !!(' + assertion + ')'):
                        probs.append('ASSERT-FAIL')
                else:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(open(p, encoding='utf-8'), 'html.parser')
                    if soup.find('script'):
                        probs.append('unexpected script in benign output')
                if probs:
                    fails.append((name, '; '.join(probs)))
            except Exception as e:
                fails.append((name, 'ERR %s %s' % (type(e).__name__, str(e)[:140])))

        # ---- idempotence ----
        p = write_case('idem.html', '<div onclick="x()"><a href="javascript:x()">c</a><p>keep</p></div>')
        run_filter(filter_py, p)
        one = open(p, 'rb').read()
        run_filter(filter_py, p)
        if open(p, 'rb').read() != one:
            fails.append(('idempotence', 'second run changed output'))
    finally:
        if driver is not None:
            driver.quit()
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(ATTACK) + len(STRESS) + len(BENIGN)
    if fails:
        print('%d FAILURES out of %d cases:' % (len(fails), total))
        for name, why in fails:
            print('  FAIL %-28s %s' % (name, why))
        sys.exit(1)
    print('ALL PASS: %d attack, %d stress, %d benign, idempotence'
          % (len(ATTACK), len(STRESS), len(BENIGN)))


if __name__ == '__main__':
    main()
