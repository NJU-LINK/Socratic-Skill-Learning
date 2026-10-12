#!/usr/bin/env python3
"""Deep browser check: for each html file pair (input, filtered output),
load the page, click dangerous links, submit dangerous forms, do an
innerHTML round-trip (mutation-XSS probe), and report whether a __xss flag
fired anywhere (top window + all frames).

Fails loud: probe errors are labeled ERROR, never folded into INERT-BOTH,
and the run aborts when the oracle control does not fire (harness broken).
"""
import sys, os, time, glob
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_argument('--headless=new')
opts.add_argument('--no-sandbox')
opts.add_argument('--disable-gpu')
opts.add_argument('--disable-dev-shm-usage')
opts.add_argument('--allow-file-access-from-files')
opts.binary_location = '/usr/bin/chromium'

CONTROL_NAME = 'zzz_control.html'  # oracle: plain <script>__xss=1</script>


def js(drv, script):
    """Return ('ok', value) or ('error', message).  Unexpected probe
    failures are errors -- NEVER aliased with 'no fire'."""
    for _ in range(8):
        try:
            try:
                drv.switch_to.alert.accept()
                time.sleep(0.1)
                continue
            except Exception:
                pass
            return ('ok', drv.execute_script(script))
        except Exception as e:
            msg = str(e)
            if 'alert' in msg.lower():
                try:
                    drv.switch_to.alert.accept()
                except Exception:
                    pass
                continue
            return ('error', repr(msg)[:160])
    return ('error', 'probe could not run (alert loop / stale driver)')


_SCAN_JS = """
  var hit=false, where='';
  function scan(w, n){
    try { if (w.__xss){ hit=true; where=n; } } catch(e){}
    try { for (var i=0;i<w.frames.length;i++) scan(w.frames[i], n+'.f'+i); } catch(e){}
  }
  scan(window,'top');
  return hit ? where : '';
"""


def probe(drv, path, deep=False):
    """Returns (fires_list, error_or_None).  fires_list entries like
    'load:top'; error is a message if any probe step could not run."""
    try:
        drv.set_page_load_timeout(6)
        drv.get('file://' + path)
        time.sleep(0.8)
    except Exception as e:
        return [], 'page load failed: ' + repr(str(e))[:120]

    def check(tag):
        status, val = js(drv, _SCAN_JS)
        if status != 'ok':
            return (None, val)
        return (val or '', None)

    res, error = [], None
    fired, err = check('load')
    if err:
        return res, err
    if fired:
        res.append('load:' + fired)
    if deep:
        js(drv, "var h=document.body.innerHTML; document.body.innerHTML=h;")
        time.sleep(0.7)
        fired, err = check('rt')
        if err:
            return res, err
        if fired:
            res.append('rt:' + fired)
        # click dangerous links / submit dangerous forms in every frame
        # (safe links would navigate away and wipe the flag; jsnav eval is
        # async so re-scan after a delay)
        js(drv, """
          function act(w){
            var d = w.document;
            var links = d.querySelectorAll('a[href]');
            for (var i=0;i<links.length;i++){
              var t = links[i].href || '';
              if (/^(javascript|vbscript|mhtml|data):/i.test(t)) {
                try { links[i].click(); } catch(e){}
              }
            }
            var els = d.querySelectorAll('button[formaction], input[formaction]');
            for (var i=0;i<els.length;i++){
              var t = els[i].getAttribute('formaction') || '';
              if (/^(javascript|vbscript|mhtml|data):/i.test(t.trim())) {
                try { els[i].click(); } catch(e){}
              }
            }
            var forms = d.querySelectorAll('form[action]');
            for (var i=0;i<forms.length;i++){
              var t = forms[i].getAttribute('action') || '';
              if (/^(javascript|vbscript|mhtml|data):/i.test(t.trim())) {
                try { forms[i].submit(); } catch(e){}
              }
            }
            for (var i=0;i<w.frames.length;i++){ try{ act(w.frames[i]); }catch(e){} }
          }
          act(window);
        """)
        time.sleep(0.7)
        fired, err = check('click')
        if err:
            return res, err
        if fired:
            res.append('click:' + fired)
    return res, error


def main(dirpath):
    drv = webdriver.Chrome(options=opts)
    try:
        control = os.path.join(dirpath, CONTROL_NAME)
        if not os.path.exists(control):
            print(f'FATAL: oracle control {CONTROL_NAME} missing; cannot trust run')
            return 2
        fires, err = probe(drv, control, deep=False)
        if err or not fires:
            print(f'FATAL: harness broken (oracle control did not fire: '
                  f'fires={fires} err={err}); run is noise, not evidence')
            return 2
        ok = inert = leaks = errors = noorig = 0
        for path in sorted(glob.glob(os.path.join(dirpath, '*.html'))):
            tag = os.path.basename(path)
            if tag == CONTROL_NAME or '.filtered' in tag or '.out' in tag:
                continue
            outpath = path.replace('.html', '.filtered.html')
            if not os.path.exists(outpath):
                continue
            orig, oerr = probe(drv, path, deep=True)
            filt, ferr = probe(drv, outpath, deep=True)
            if oerr or ferr:
                status = 'ERROR'
                errors += 1
            elif orig and not filt:
                status = 'OK'
                ok += 1
            elif not orig and not filt:
                status = 'INERT-BOTH'
                inert += 1
            elif filt:
                status = 'LEAK!!!'
                leaks += 1
            else:
                status = 'NO-ORIG-FIRE'
                noorig += 1
            extra = f' oerr={oerr} ferr={ferr}' if (oerr or ferr) else ''
            print(f'{status:11s} {tag:42s} orig={orig} filtered={filt}{extra}')
        valid = 'VALID' if errors == 0 else 'INVALID (errors present)'
        print(f'--- summary: OK={ok} INERT-BOTH={inert} LEAK={leaks} '
              f'ERROR={errors} NO-ORIG-FIRE={noorig} [{valid}]')
        return 0 if (leaks == 0 and errors == 0) else 1
    finally:
        drv.quit()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))