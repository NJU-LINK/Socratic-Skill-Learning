#!/usr/bin/env python3
"""url_boundary_probe.py -- generate a URL-layer boundary matrix for an HTML
JavaScript filter and verify every filtered output is inert in a real browser.

The point of this probe is NOT "more payloads from your intuition"; it is the
enumerated input-space of ONE pipeline step (the browser's URL parser
preprocessing): for every character U+0000..U+001F and U+0020, exercise a
leading prefix and a trailing suffix of an executable URL in every URL-bearing
construct the filter must cover.

Usage:
    1. python3 url_boundary_probe.py matrix/           # generates x.html cases
    2. for f in matrix/*.html; do python3 filter.py "$f"; done
       (or copy each to x.filtered.html after filtering)
    3. python3 deep_check.py matrix/                   # browser verdicts

Every case whose ORIGINAL fires in Chromium must have an inert filtered
version.  Currently known result (Chromium 150): ALL leading C0/space
prefixes on href/javascript: execute after the URL parser trims them, so the
filter must trim ^[\\x00-\\x20]+ before the scheme check (Python str.lstrip
is NOT enough: it misses U+0001-0008 and U+000E-001B).
"""
import os
import sys

CONTEXTS = {
    # name: (html template with {N} for the numeric character reference)
    "href": '<!DOCTYPE html><html><body><a href="&#{N};javascript:__xss=1">go</a></body></html>',
    "meta": '<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0;url=&#{N};javascript:__xss=1"></head><body><p>x</p></body></html>',
    "form_action": '<!DOCTYPE html><html><body><form action="&#{N};javascript:__xss=1"><input type="submit"></form></body></html>',
    "srcdoc": '<!DOCTYPE html><html><body><iframe srcdoc="<a href=&quot;&#{N};javascript:__xss=1&quot;>in</a>"></iframe></body></html>',
    "svg_xlink": '<!DOCTYPE html><html><body><svg><a xlink:href="&#{N};javascript:__xss=1"><text>go</text></a></svg></body></html>',
}


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    for n in list(range(0x00, 0x20)) + [0x20]:
        for name, template in CONTEXTS.items():
            html = template.replace("{N}", str(n))
            with open(os.path.join(outdir, f"c{n:02x}_{name}.html"), "w") as fh:
                fh.write(html)
    print(f"wrote {len(range(0x20)) * len(CONTEXTS)} cases to {outdir}")
    print("then: filter each (x.html -> x.filtered.html) and run deep_check.py")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "matrix")