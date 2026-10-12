#!/usr/bin/env python3
"""Verification script for HTML filter.

Tests idempotency, safety, and preservation across the family axes.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from filter import filter_html


def test_idempotency(name, html):
    """Test that filtering is idempotent."""
    filtered1 = filter_html(html)
    filtered2 = filter_html(filtered1)
    if filtered1 != filtered2:
        print(f"FAIL: {name} - Not idempotent")
        return False
    return True


def test_dangerous_removed(name, html, patterns):
    """Test that dangerous patterns are removed."""
    filtered = filter_html(html)
    for p in patterns:
        if p.lower() in filtered.lower():
            print(f"FAIL: {name} - Pattern still present: {p}")
            return False
    return True


def test_safe_preserved(name, html):
    """Test that safe content is preserved byte-identical."""
    filtered = filter_html(html)
    if html != filtered:
        print(f"FAIL: {name} - Content changed")
        return False
    return True


def run_all_tests():
    """Run all verification tests."""
    passed = 0
    failed = 0
    
    # Core tests
    tests = [
        ("Script removal", "<script>alert(1)</script><p>Safe</p>", ["<script"], True),
        ("Event handler", '<a href="/safe" onclick="alert(1)">Link</a>', ["onclick"], True),
        ("JS URL", '<a href="javascript:alert(1)">Link</a>', ["href="], True),
        ("Safe content", '<div class="test"><p>Hello</p></div>', [], False),
        ("Self-closing", '<br/><hr/>', [], False),
        ("iframe", '<iframe src="x"></iframe>', ["<iframe"], True),
        ("embed", '<embed src="x">', ["<embed"], True),
        ("object", '<object data="x"></object>', ["<object"], True),
        ("Style element", '<style>body{color:red}</style>', [], False),
        ("data image", '<img src="data:image/png,base64,AAAA">', [], False),
        ("Case on*", '<a ONCLICK="x">', ["onclick"], True),
    ]
    
    for name, html, bad_patterns, should_change in tests:
        if should_change:
            if test_dangerous_removed(name, html, bad_patterns):
                passed += 1
            else:
                failed += 1
        else:
            if test_safe_preserved(name, html):
                passed += 1
            else:
                failed += 1
    
    # Regression tests from iteration 1-3
    regressions = [
        ("Nested containers", 
         '<object><iframe>x</iframe></object><p>survives?</p>',
         lambda r: '<p>survives?</p>' in r),
        
        ("Meta refresh whitespace",
         '<meta http-equiv="refresh" content="0; URL = jav&#x61;script:alert(1)">',
         lambda r: 'meta' not in r.lower()),
        
        ("CSS url() bad",
         '<div style="background:url(javascript:alert(1))">x</div>',
         lambda r: 'style=' not in r.lower()),
        
        ("CSS url() good",
         '<p style="color:red">x</p>',
         lambda r: 'style=' in r.lower()),
        
        ("Set container",
         '<set attributeName="xlink:href" to="javascript:alert(1)">content</set>',
         lambda r: 'set' not in r.lower() and 'content' not in r),
        
        ("Entity+newline href",
         '<a href="jav&#x61;\nscript:alert(1)">link</a>',
         lambda r: 'href=' not in r.lower()),
        
        ("Safe data URL",
         '<img src="data:image/png;base64,AAAA" alt="logo">',
         lambda r: 'src=' in r.lower()),
        
        ("Foreign object",
         '<foreignObject><body onload="alert(1)">boom</body></foreignObject>',
         lambda r: 'foreignObject' not in r and 'onload' not in r.lower()),
        
        ("Annotation XML",
         '<math><annotation-xml encoding="text/html"><img src=x onerror=alert(1)></annotation-xml><msup><mi>a</mi></msup></math>',
         lambda r: 'annotation-xml' not in r and 'msup' in r and 'onerror' not in r.lower()),
        
        ("Rect onclick",
         '<rect width="10" onclick="evil()">',
         lambda r: 'onclick' not in r.lower() and 'width=' in r.lower()),
        
        ("MathML preserved",
         '<math><msup><mi>a</mi><mn>2</mn></msup></math>',
         lambda r: 'math' in r.lower()),
    ]
    
    for name, html, check in regressions:
        result = filter_html(html)
        if check(result):
            passed += 1
        else:
            print(f"FAIL: {name}")
            print(f"  Output: {result[:100]}")
            failed += 1
    
    # Idempotency tests
    idem_tests = [
        '<div><script>alert(1)</script></div>',
        '<br/><hr/>',
    ]
    for html in idem_tests:
        if test_idempotency("Idempotency", html):
            passed += 1
        else:
            failed += 1
    
    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    return failed == 0


if __name__ == '__main__':
    sys.exit(0 if run_all_tests() else 1)
