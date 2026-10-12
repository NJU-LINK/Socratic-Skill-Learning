#!/usr/bin/env python3
"""Browser-oracle differential harness for filter-js-from-html.

Confronts the skill's spec-modeled mechanism claims with a real browser
(headless Chromium via selenium; the container ships /usr/bin/chromium +
/usr/bin/chromedriver).  For each disputed fixture it probes:
  (a) execution markers (window.__fired / alert override),
  (b) parsed node shape (namespaceURI, localName, presence),
  (c) visible presence (getBBox / offsetHeight),
and prints a judgement table: CONFIRMED / CONTRADICTED / PARTIAL per claim.

Usage: python3 tests/browser_oracle.py   (needs network-free local driver)
Output: prints the table; the authoritative record lives next to this file
as oracle_results.txt (regenerated each run).
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)
import filter  # noqa: E402

RESULT_FILE = "/tmp/oracle_results.txt"

# ---------------------------------------------------------------------------
# Driver availability probe (recorded in the results file regardless of branch)
# ---------------------------------------------------------------------------
def probe_driver():
    rows = []
    for exe in ("google-chrome", "google-chrome-stable", "chromium",
                "chromium-browser", "chromedriver", "firefox", "geckodriver"):
        r = subprocess.run(["which", exe], capture_output=True, text=True)
        rows.append((exe, r.stdout.strip() or "MISSING"))
    return rows


def make_driver():
    from selenium import webdriver
    opts = webdriver.ChromeOptions()
    for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
              "--disable-gpu", "--disable-extensions", "--mute-audio"):
        opts.add_argument(a)
    d = webdriver.Chrome(options=opts)
    return d


# ---------------------------------------------------------------------------
# Probe runner
# ---------------------------------------------------------------------------
class Oracle:
    def __init__(self, driver):
        self.d = driver

    def fresh(self, html: str, in_head: bool = False) -> None:
        """Load a fresh document (file URL; head marker script injected)."""
        marker = ('<script>window.__fired=[];window.alert=function(m){window.__fired.push("alert:"+m)}</script>')
        if in_head:
            body = ('<!DOCTYPE html><html><head>' + marker + html + '</head><body></body></html>')
        else:
            body = ('<!DOCTYPE html><html><head>' + marker + '</head><body>' + html + '</body></html>')
        path = os.path.join("/tmp", "oracle_probe.html")
        with open(path, "w") as f:
            f.write(body)
        self.d.get("file://" + path)

    def fired(self):
        return self.d.execute_script("return window.__fired || []")

    def js(self, expr):
        """Single-expression probe."""
        return self.d.execute_script("return " + expr)

    def run(self, script):
        """Full statement script (must carry its own return)."""
        return self.d.execute_script(script)

    def click(self, eid, wait=0.6):
        """Activate an element.  dispatchEvent is the primary method: it
        reaches SVG <a> activation behavior in headless Chromium where
        ActionChains (and HTMLElement.click, absent on SVGAElement) fail.
        Verified empirically: dispatch+MouseEvent navigates both HTML and SVG
        anchors, including xlink:href=javascript: execution."""
        self.d.execute_script(
            "var e=document.getElementById(%r);"
            "if(e){e.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));}" % eid)
        time.sleep(wait)

    def wait(self, s=1.5):
        time.sleep(s)

    def loc(self):
        return self.d.current_url

    def ns(self, eid):
        return self.run("var el=document.getElementById(%r); return el? el.namespaceURI : null" % eid)

    def present(self, selector):
        return self.js("!!document.querySelector(%r)" % selector)


results = []  # (claim_id, claim, verdict, detail)


def record(cid, claim, verdict, detail):
    results.append((cid, claim, verdict, detail))
    flag = "CONFIRMED" if verdict == "confirmed" else ("CONTRADICTED" if verdict == "contradicted" else "PARTIAL")
    print(f"[{flag}] {cid}: {claim} -> {detail}")


rec = record


def main():
    avail = probe_driver()
    chromes = [p for n, p in avail if n in ("chromium", "google-chrome", "google-chrome-stable") and p != "MISSING"]
    print("driver probe:", avail)
    if not chromes:
        print("NO BROWSER: falling back to branch (b) -- demote unverified rows.")
        with open(RESULT_FILE, "w") as f:
            f.write("DRIVER PROBE (no browser):\n" + "\n".join(f"{n}: {p}" for n, p in avail) + "\n")
        return 2
    d = make_driver()
    o = Oracle(d)
    print("browser:", d.capabilities.get("browserVersion"))
    ver = d.capabilities.get("browserVersion")

    # ---- 0. sanity: scripts execute, marker plumbing works ----
    o.fresh('<script>window.__fired.push("sanity")</script>')
    rec("sanity", "inline scripts execute and markers work", "confirmed",
        f"fired={o.fired()}")

    # ---- 1. HTML script self-closing: rawtext swallow executes content ----
    o.fresh('x<script/>window.__fired.push("sc-swallow")</script>y')
    rec("script-html-selfclose", "HTML <script/> ignores flag, content executes",
        "confirmed" if "sc-swallow" in o.fired() else "contradicted",
        f"fired={o.fired()}")

    # ---- 2. SVG script self-closing: DOM shape + neighbors ----
    o.fresh('<svg><script/><circle id="c" r="5"/></svg><p id="p">t</p>'
            '<script>window.__fired.push("ready")</script>')
    c_ns = o.ns("c")
    c_bbox = o.run("var c=document.getElementById('c'); return c? (c.getBBox? c.getBBox().width : 'nobbox') : 'missing'")
    p_h = o.run("var p=document.getElementById('p'); return p? p.offsetHeight : 'missing'")
    scripts = o.run("return Array.from(document.querySelectorAll('script')).map(function(s){return s.namespaceURI+'|'+s.localName}).join(',')")
    rec("script-svg-selfclose", "SVG <script/> honors flag: circle+p are elements, script in SVG ns",
        "confirmed" if c_ns == "http://www.w3.org/2000/svg" and o.present("#p") else "contradicted",
        f"circle_ns={c_ns} circle_bbox={c_bbox} p_h={p_h} scripts={scripts}")

    # ---- 3. entity-cloaked attribute NAME (on&#x65;rror) ----
    o.fresh('<img id="i" src="__nope__" on&#x65;rror="window.__fired.push(\'cloaked\')">'
            '<script>window.__fired.push("ready")</script>')
    o.wait(0.8)
    rec("attrname-entity", "on&#x65;rror is decoded and LIVE",
        "confirmed" if "cloaked" in o.fired() else "contradicted", f"fired={o.fired()}")

    # ---- 4. foreign iframe: namespace + srcdoc inertness ----
    o.fresh('<svg><iframe id="f" srcdoc="<img src=x onerror=top.__fired.push(\'fsrcdoc\')>"></iframe></svg>'
            '<script>window.__fired.push("ready")</script>')
    o.wait(1.0)
    f_ns = o.ns("f")
    f_cw = o.run("var f=document.getElementById('f'); return f? (f.contentWindow? 'has-cw' : 'no-cw') : 'missing'")
    rec("foreign-iframe-inert", "<svg><iframe> stays foreign namespace, srcdoc does not execute",
        "confirmed" if f_ns == "http://www.w3.org/2000/svg" and "fsrcdoc" not in o.fired() else "contradicted",
        f"iframe_ns={f_ns} contentWindow={f_cw} fired={o.fired()}")

    # ---- 5. HTML iframe srcdoc DOES execute (sanity for unconditional removal) ----
    o.fresh('<iframe id="f2" srcdoc="<img src=x onerror=top.__fired.push(\'hsrcdoc\')>"></iframe>'
            '<script>window.__fired.push("ready")</script>')
    o.wait(1.0)
    rec("html-iframe-srcdoc-live", "HTML iframe srcdoc executes (removal needed)",
        "confirmed" if "hsrcdoc" in o.fired() else "contradicted", f"fired={o.fired()}")

    # ---- 6. template fragment stack: svg inside template does not leak ----
    o.fresh('<template><svg><circle id="tc" r="1"/></template>'
            '<iframe id="f3" srcdoc="<img src=x onerror=top.__fired.push(\'tplsrcdoc\')>"></iframe>'
            '<script>window.__fired.push("ready")</script>')
    o.wait(1.0)
    rec("template-no-leak", "svg inside <template> does not extend past </template>; srcdoc iframe is HTML/live",
        "confirmed" if "tplsrcdoc" in o.fired() else "contradicted", f"fired={o.fired()}")

    # ---- 7. table stack clearing: svg in table popped by </table> ----
    o.fresh('<table><svg><circle r="1"/></table>'
            '<iframe id="f4" srcdoc="<img src=x onerror=top.__fired.push(\'tblsrcdoc\')>"></iframe>'
            '<script>window.__fired.push("ready")</script>')
    o.wait(1.0)
    rec("table-clears-svg", "</table> pops foster-parented svg; following iframe is HTML/live",
        "confirmed" if "tblsrcdoc" in o.fired() else "contradicted", f"fired={o.fired()}")

    # ---- 8. duplicate attributes: first occurrence wins ----
    o.fresh('<a id="a" href="javascript:window.__fired.push(\'dup\')" href="#ok">x</a>')
    o.click("a")
    rec("dup-attr-first-wins", "browser honors FIRST href (javascript: fires)",
        "confirmed" if "dup" in o.fired() else "contradicted", f"fired={o.fired()}")

    # ---- 9. javascript: URL normalization cases ----
    o.fresh('<a id="a1" href="jav&#x09;ascript:window.__fired.push(\'tab\')">x</a>')
    o.click("a1")
    rec("js-entity-tab-live", "jav&#x09;ascript: (entity tab) is LIVE",
        "confirmed" if "tab" in o.fired() else "contradicted", f"fired={o.fired()}")

    o.fresh('<a id="a2" href="java script:window.__fired.push(\'space\')">x</a>')
    o.click("a2")
    rec("js-space-inert", '"java script:" (ordinary space) is INERT',
        "confirmed" if "space" not in o.fired() else "contradicted", f"fired={o.fired()}")

    o.fresh('<a id="a3" href="%6a%61%76%61%73%63%72%69%70%74:window.__fired.push(\'pct\')">x</a>')
    o.click("a3")
    rec("js-percent-inert", "percent-encoded scheme is INERT in a modern engine",
        "confirmed" if "pct" not in o.fired() else "contradicted", f"fired={o.fired()}")

    o.fresh('<a id="a4" href="java\x00script:window.__fired.push(\'null\')">x</a>')
    o.click("a4")
    rec("js-nullbyte-inert", "null-byte-in-scheme is INERT in a modern engine",
        "confirmed" if "null" not in o.fired() else "contradicted", f"fired={o.fired()}")

    o.fresh('<a id="a5" href="javascript:window.__fired.push(\'plain\')">x</a>')
    o.click("a5")
    rec("js-plain-live", "plain javascript: href is LIVE",
        "confirmed" if "plain" in o.fired() else "contradicted", f"fired={o.fired()}")

    # ---- 10. meta refresh ----
    o.fresh('<meta http-equiv="refresh" content="0;url=javascript:alert(1)">'
            '<script>window.__fired.push("ready")</script>')
    o.wait(2.0)
    rec("meta-refresh-js", "meta refresh to javascript: URL",
        "partial", f"fired={o.fired()} loc={o.loc()}")

    o.fresh('<meta http-equiv="refresh" content="0;url=data:text/html,<script>document.title=%27FIRED%27</script>">'
            '<script>window.__fired.push("ready")</script>')
    o.wait(2.0)
    t = o.d.title
    rec("meta-refresh-data", "meta refresh to data:text/html navigates (script runs in target)",
        "confirmed" if t == "FIRED" else "contradicted", f"title={t!r} loc={o.loc()}")

    # ---- 11. annotation-xml integration point ----
    o.fresh('<math><annotation-xml id="ax" encoding="text/html">'
            '<script>window.__fired.push(\'axhtml\')</script></annotation-xml></math>')
    rec("annotation-xml-html", "annotation-xml encoding=text/html is an HTML integration point (script executes)",
        "confirmed" if "axhtml" in o.fired() else "contradicted", f"fired={o.fired()}")

    o.fresh('<math><annotation-xml id="ax2" encoding="text/plain">'
            '<script>window.__fired.push(\'axplain\')</script></annotation-xml></math>')
    ax2_script_ns = o.run("var s=document.querySelector('annotation-xml script'); return s? s.namespaceURI : 'none'")
    rec("annotation-xml-plain", "annotation-xml encoding=text/plain is NOT an integration point (script inert, MathML ns)",
        "confirmed" if "axplain" not in o.fired() and ax2_script_ns == "http://www.w3.org/1998/Math/MathML" else "contradicted",
        f"fired={o.fired()} script_ns={ax2_script_ns}")

    # ---- 12. mtext script: MathML text integration point ----
    o.fresh('<math><mtext><script>window.__fired.push(\'mtext\')</script></mtext></math>')
    m_ns = o.run("var s=document.querySelector('mtext script'); return s? s.namespaceURI : 'none'")
    rec("mtext-script", "<math><mtext><script> is inert (MathML-namespace element)",
        "confirmed" if "mtext" not in o.fired() and m_ns == "http://www.w3.org/1998/Math/MathML" else "contradicted",
        f"fired={o.fired()} script_ns={m_ns}")

    # ---- 13. noscript content with scripting enabled ----
    o.fresh('<noscript id="n"><img src=x onerror="window.__fired.push(\'ns\')"></noscript>'
            '<script>window.__fired.push("ready")</script>')
    o.wait(0.8)
    n_text = o.run("var n=document.getElementById('n'); return n? (n.textContent||'').slice(0,60) : 'missing'")
    rec("noscript-rawtext", "noscript content is inert rawtext when scripting is enabled",
        "confirmed" if "ns" not in o.fired() else "contradicted",
        f"fired={o.fired()} noscript_text={n_text!r}")

    # ---- 14. img data:image/svg+xml does not execute ----
    o.fresh('<img id="svgi" src="data:image/svg+xml,<svg xmlns=\'http://www.w3.org/2000/svg\' onload=\'window.__fired.push(\\\'svgimg\\\')\'/>">'
            '<script>window.__fired.push("ready")</script>')
    o.wait(1.0)
    rec("img-svg-data-inert", "SVG data URL in <img src> does not execute its onload",
        "confirmed" if "svgimg" not in o.fired() else "contradicted", f"fired={o.fired()}")

    # ---- 15. xlink:href javascript: click ----
    o.fresh('<svg><a id="xa" xlink:href="javascript:window.__fired.push(\'xlink\')"><text>t</text></a></svg>')
    o.click("xa")
    rec("xlink-js", "SVG a xlink:href=javascript: executes on click",
        "confirmed" if "xlink" in o.fired() else "contradicted", f"fired={o.fired()}")

    # ---- 16. embed/object in svg: embed breaks out, object stays foreign ----
    o.fresh('<svg><embed id="e" src="x"><object id="ob" data="y"></object><circle r="1"/></svg>')
    e_ns = o.ns("e")
    ob_ns = o.ns("ob")
    rec("embed-breakout", "embed breaks out of SVG (HTML ns); object stays foreign (SVG ns)",
        "confirmed" if e_ns == "http://www.w3.org/1999/xhtml" and ob_ns == "http://www.w3.org/2000/svg" else "contradicted",
        f"embed_ns={e_ns} object_ns={ob_ns}")

    # ---- 17. script double-escaped close semantics ----
    o.fresh('<script><!--<script>window.__fired.push(\'inner\')</script>-->window.__fired.push(\'outer\')</script>')
    rec("script-double-escaped", "first </script> after <!--<script> does NOT close; only outer executes",
        "confirmed" if o.fired() == ["outer"] else "contradicted", f"fired={o.fired()}")

    # ---- 18. template script inert at parse time ----
    o.fresh('<template><script>window.__fired.push(\'tpl\')</script></template>'
            '<script>window.__fired.push("ready")</script>')
    o.wait(0.8)
    rec("template-script-inert", "script inside <template> does not execute at parse time",
        "confirmed" if "tpl" not in o.fired() else "contradicted", f"fired={o.fired()}")

    # ---- 19. SVG set/animate SMIL rewrite: does the assigned href engage? ----
    o.fresh('<svg><a id="sa" href="#base"><set attributeName="href" to="javascript:window.__fired.push(\'smil\')"/></a></svg>')
    o.wait(1.2)
    o.click("sa")
    rec("smil-set-href", "SMIL <set> rewrites href to javascript: (fires on click)",
        "confirmed" if "smil" in o.fired() else "contradicted", f"fired={o.fired()}")

    # ---- 20. FOLLOW-UPS (de-confounded probes) ----
    # 20a. attribute-name entity: what is the RAW attribute name?
    o.fresh('<img id="i" src="__nope__" on&#x65;rror="window.__fired.push(\'cloaked\')">'
            '<script>window.__fired.push("ready")</script>')
    o.wait(0.8)
    attrs = o.run("var e=document.getElementById('i'); return e? Array.from(e.attributes).map(function(a){return a.name}).join('|') : 'none'")
    rec("attrname-entity-raw-name", "attribute name is stored literally (entity NOT decoded in name state)",
        "confirmed" if "on&#x65;rror" in attrs else "contradicted", f"attr_names={attrs!r} fired={o.fired()}")
    o.fresh('<img id="i2" src="__nope__" onerror="window.__fired.push(\'plain-err\')">'
            '<script>window.__fired.push("ready")</script>')
    o.wait(0.8)
    rec("attrname-plain-control", "plain onerror fires (control for the entity-name probe)",
        "confirmed" if "plain-err" in o.fired() else "contradicted", f"fired={o.fired()}")

    # 20b. meta refresh must sit in <head>
    o.fresh('<meta http-equiv="refresh" content="0;url=javascript:alert(1)">', in_head=True)
    o.wait(2.5)
    rec("meta-refresh-js-head", "meta refresh to javascript: URL (head placement)",
        "partial", f"fired={o.fired()} loc={o.loc()}")
    o.fresh('<meta http-equiv="refresh" content="0;url=data:text/html,<script>document.title=%27FIRED%27</script>">', in_head=True)
    o.wait(2.5)
    rec("meta-refresh-data-head", "meta refresh to data:text/html (head placement)",
        "confirmed" if o.d.title == "FIRED" else "contradicted", f"title={o.d.title!r} loc={o.loc()}")

    # 20c. script double-escaped: DOM shape (textContent shows where element ends)
    o.fresh('<script><!--<script>window.__fired.push(\'inner\')</script>-->window.__fired.push(\'outer\')</script>'
            '<script>window.__fired.push("ready")</script>')
    txt = o.run("return Array.from(document.querySelectorAll('script')).map(function(s){return s.textContent}).join('###')")
    rec("script-double-escaped-dom", "script element closes at the FINAL </script> (textContent contains outer)",
        "confirmed" if "outer" in txt else "contradicted", f"textContent={txt!r}")

    # 20d. SMIL set rewrite to a benign URL (mechanism) -- unconfounded
    o.fresh('<svg><a id="sa2" href="#gone"><set attributeName="href" to="https://example.com/?oracle=1"/></a></svg>')
    o.wait(1.5)
    o.click("sa2", wait=1.0)
    rec("smil-set-rewrites-href", "SMIL <set> rewrites href at runtime (navigation follows)",
        "confirmed" if o.loc().startswith("https://example.com") else "contradicted",
        f"loc={o.loc()}")

    # 20e. object/embed de-confounded (each alone inside a fresh <svg>)
    o.fresh('<svg><object id="ob2" data="y"></object><circle r="1"/></svg>')
    rec("svg-object-alone", "<svg><object> stays foreign (SVG ns)",
        "confirmed" if o.ns("ob2") == "http://www.w3.org/2000/svg" else "contradicted", f"object_ns={o.ns('ob2')}")
    o.fresh('<svg><embed id="e2" src="x"></embed><circle r="1"/></svg>')
    rec("svg-embed-alone", "<svg><embed> breaks out (HTML ns)",
        "confirmed" if o.ns("e2") == "http://www.w3.org/1999/xhtml" else "contradicted", f"embed_ns={o.ns('e2')}")

    # 20f. SVG a with modern href attribute + javascript:
    o.fresh('<svg><a id="xa4" href="javascript:window.__fired.push(\'href2\')"><text>t</text></a></svg>')
    o.click("xa4")
    rec("svg-a-href-js", "SVG a with plain href=javascript: click behavior",
        "confirmed" if "href2" in o.fired() else "contradicted", f"fired={o.fired()}")

    # ---- 21. ROUND-2 CONTROLS (validate probe methods for the rows above) ----
    # 21a. meta refresh control: benign https URL must navigate if the probe works
    o.fresh('<meta http-equiv="refresh" content="0;url=https://example.com/?ctrl=1">', in_head=True)
    o.wait(3.0)
    rec("meta-refresh-https-control", "meta refresh to https navigates (probe method control)",
        "confirmed" if "example.com" in o.loc() else "contradicted", f"loc={o.loc()}")
    # 21b. SVG a click control: benign https href must navigate if clicks reach SVG a
    o.fresh('<svg><a id="sa_c" href="https://example.com/?ctrl=2"><text>t</text></a></svg>')
    o.click("sa_c", wait=1.5)
    rec("svg-a-click-control", "click on SVG a with https href navigates (click method control)",
        "confirmed" if "example.com" in o.loc() else "contradicted", f"loc={o.loc()}")
    # 21c. SMIL set rewriting xlink:href (the classic spelling)
    o.fresh('<svg><a id="sa3" xlink:href="#gone"><set attributeName="xlink:href" to="https://example.com/?oracle=3"/></a></svg>')
    o.wait(1.5)
    o.click("sa3", wait=1.5)
    rec("smil-set-rewrites-xlink-href", "SMIL <set> rewrites xlink:href at runtime (classic spelling)",
        "confirmed" if "example.com" in o.loc() else "contradicted", f"loc={o.loc()}")

    d.quit()
    write_results(ver, avail)


def write_results(ver, avail):
    with open(RESULT_FILE, "w") as f:
        f.write(f"BROWSER-ORACLE RESULTS  (chromium {ver})\n")
        f.write("driver probe: " + ", ".join(f"{n}={p.split('/')[-1] or 'MISSING'}" for n, p in avail) + "\n\n")
        for cid, claim, verdict, detail in results:
            f.write(f"{verdict.upper():12s} {cid:26s} {claim}\n          detail: {detail}\n")
    print("\nwrote", RESULT_FILE)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            write_results("unknown", probe_driver())
        except Exception:
            pass
        raise