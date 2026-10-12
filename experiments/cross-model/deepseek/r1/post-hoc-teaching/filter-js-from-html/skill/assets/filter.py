#!/usr/bin/env python3
"""filter.py -- remove executable JavaScript behavior from an HTML file, in place.

Usage: python3 filter.py input.html

Strategy
--------
* Parse with html5lib (the HTML5 tree-construction algorithm: browser-grade
  error recovery, namespace-aware SVG/MathML).  html5lib is REQUIRED: a
  parser weaker than the browser's could certify content the browser would
  execute, so the filter fails closed (exit 3) when it is unavailable
  instead of emitting best-effort output.  html5lib is pure Python; the
  vendored copy under ./vendor is used automatically.
* Normalization, not byte-matching: the output is a re-serialized document
  that is *functionally* identical to the input except that every construct
  that can execute script has been neutralized.
* Defense in depth:
    - remove <script> elements (HTML, SVG, MathML namespaces)
    - drop all on* event-handler attributes (any element, any namespace)
    - drop URL-bearing attributes (href/src/action/formaction/poster/...)
      whose value resolves to an executable scheme after browser-equivalent
      normalization (see _dangerous_url_value)
    - REMOVE the whole element for construct-inherent danger carriers:
      <script>, <meta http-equiv=refresh> with an executable URL, <style>
      whose text contains executable CSS
    - REMOVE the whole style attribute when it contains executable CSS
      (url(javascript:...), expression(...), dangerous @import); safe style
      attributes are preserved exactly
    - sanitize <iframe srcdoc> content recursively (depth-capped)
    - drop SVG animation attributeName targeting event handlers / href
    - parse fragments containing <frameset> in a frameset fragment context so
      frameset/frame structure survives normalization and frame src= and
      frameset onload= are neutralized (a div-context parse drops them and
      the no-change path would leave the raw dangerous bytes)
    - re-parse / re-sanitize in a fixpoint loop so that constructs that only
      become dangerous after serialization + re-parsing are caught
    - harden <noscript> regions (early '</noscript' promotion)
    - preserve the doctype (html5lib drops it by default)
* Fail-loud policy: NO failure mode may be represented by the same output as
  success.  The tree walk is iterative (deep nesting cannot RecursionError);
  exceptions PROPAGATE before any write (input file untouched); the only
  legitimate "no change" is a completed walk that changed nothing.
"""

import os
import re
import sys
import urllib.parse

# Deeply nested documents parse fine in html5lib (iterative tokenizer) but can
# blow a recursive sanitizer walk.  The walk is iterative; this limit is a
# belt-and-braces budget for the remaining small recursion (srcdoc chains are
# additionally depth-capped) so RecursionError can never masquerade as "no
# change".
sys.setrecursionlimit(10000)

# ---------------------------------------------------------------------------
# parser selection : html5lib (vendored copy first, then installed copy)
# ---------------------------------------------------------------------------
_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if os.path.isdir(_VENDOR):
    sys.path.insert(0, _VENDOR)

try:
    import html5lib
    from html5lib import getTreeWalker
    from html5lib.serializer import HTMLSerializer as _HTMLSerializer
    import xml.etree.ElementTree as _ET
    _HAS_HTML5LIB = True
except Exception:  # pragma: no cover - fail-closed path
    _HAS_HTML5LIB = False

# No fallback parser.  A parser weaker than the browser's can certify
# content that the browser will execute (mXSS relies on exactly that gap), so
# the filter FAILS CLOSED (exit 3, file untouched) when html5lib is
# unavailable.  Bootstrap: pip install --target=./vendor html5lib

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------
URL_ATTRS = frozenset(
    [
        "href", "src", "action", "formaction", "poster", "background",
        "dynsrc", "lowsrc", "data", "code", "codebase",
    ]
)

_CTRL_STRIP = re.compile(r"[\t\n\r\x00\ufffd]")
# WHATWG URL parser preprocessing: leading/trailing C0 controls (U+0000-001F)
# and ASCII space are removed BEFORE the scheme is scanned.  Python str.lstrip
# only removes isspace() characters and would miss U+0001-0008 / U+000E-001B.
_URL_TRIM = re.compile(r"^[\x00-\x20]+|[\x00-\x20]+$")
_SCHEME_RE = re.compile(r"([A-Za-z][A-Za-z0-9+\-.]*)\s*:")


def _unpercent(v):
    try:
        return urllib.parse.unquote(v)
    except Exception:
        return v


def _dangerous_url_value(value):
    """Return the dangerous scheme name if `value` can execute script,
    else None.  Invariant: the normalizer may strip MORE than the browser's
    URL parser (every divergence adds drops) but never LESS.  Pipeline:
    strip tabs/newlines/NUL/U+FFFD anywhere -> trim leading/trailing
    C0+space -> percent-decode -> trim again -> scheme scan."""
    if not value:
        return None
    v = _CTRL_STRIP.sub("", value)
    v = _URL_TRIM.sub("", v)
    v = _unpercent(v)
    v = _URL_TRIM.sub("", v)
    m = _SCHEME_RE.match(v)
    if not m:
        return None
    scheme = m.group(1).lower()
    if scheme in ("javascript", "vbscript", "mhtml"):
        return scheme
    if scheme == "data":
        rest = v[m.end():]
        head = rest.split(",", 1)[0] if "," in rest else rest
        mediatype = head.split(";", 1)[0].strip().lower()
        if mediatype.startswith("image/") and "svg" not in mediatype:
            return None
        return "data"
    return None


# ---------------------------------------------------------------------------
# CSS danger detection (style attributes and <style> text)
# ---------------------------------------------------------------------------
def _find_block(css, start):
    """From `start` (position of keyword match), locate the opening paren and
    its matching close; returns (open_idx, close_idx one past final ')')."""
    open_p = css.find("(", start)
    if open_p < 0:
        return (start, len(css))
    depth = 1
    j = open_p + 1
    while j < len(css) and depth:
        c = css[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        j += 1
    return (open_p, j)


def _css_spans(css):
    """Return [(start, end), ...] of dangerous CSS fragments, or [] if the
    CSS is safe.  Detection tolerates comments, tabs/newlines/NULs, quotes
    and percent-encoding inside url() values."""
    spans = []
    i = 0
    while True:
        m = re.search(r"(?i)url\s*\(", css[i:])
        if not m:
            break
        start = i + m.start()
        open_p, close = _find_block(css, start)
        inner = css[open_p + 1: max(close - 1, open_p + 1)]
        probe = re.sub(r"/\*.*?\*/", "", inner, flags=re.S)
        probe = _CTRL_STRIP.sub("", probe).strip().strip("\"'")
        probe = _unpercent(probe).lower().lstrip()
        if probe.startswith(("javascript:", "vbscript:")):
            spans.append((start, close))
            i = close
        else:
            i = open_p + 1
    i = 0
    while True:
        m = re.search(r"(?i)\bexpression\s*\(", css[i:])
        if not m:
            break
        start = i + m.start()
        open_p, close = _find_block(css, start)
        spans.append((start, close))
        i = close
    i = 0
    while True:
        m = re.search(r"(?i)@import\s*(\"[^\"]*\"|'[^']*')", css[i:])
        if not m:
            break
        start = i + m.start()
        url = m.group(1)[1:-1]
        probe = _unpercent(_CTRL_STRIP.sub("", url)).lower().lstrip()
        end = m.end()
        if probe.startswith(("javascript:", "vbscript:")) or (
            probe.startswith("data:") and "text/" in probe
        ):
            semi = css.find(";", end)
            if semi >= 0:
                end = semi + 1
            spans.append((start, end))
        i = end
    return spans


# ---------------------------------------------------------------------------
# meta refresh
# ---------------------------------------------------------------------------
_META_URL_RE = re.compile(
    r"(?i)\burl\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s;]*))"
)


def _meta_refresh_dangerous(content):
    m = _META_URL_RE.search(content or "")
    if not m:
        return False
    url = m.group(1) or m.group(2) or m.group(3) or ""
    return _dangerous_url_value(url) is not None


_ON_ATTR_RE = re.compile(r"^on\w+$", re.I)
_SRC_SET_DANGER = re.compile(r"(?i)(?:javascript|vbscript)\s*:|data\s*:\s*text/")
_ANIM_ATTR_DANGER = re.compile(r"(?i)(^|:)(on\w+|href)$")
_FRAMESET_RE = re.compile(r"(?is)<frameset\b|<frame\b")
SRCDOC_MAX_DEPTH = 64
# foreignObject and annotation-xml (encoding=text/html) are HTML integration
# points whose RAW content can carry HTML (including <body onload>, whose
# attributes the browser merges onto the real body and fires -- VERIFIED in
# Chromium).  The tree parse may structurally lose that danger, so dangerous
# blocks are removed from the RAW input text BEFORE parsing.  Extent finding
# is tokenizer-faithful (quotes and comments are opaque, an end tag only
# counts outside them, self-closing /> is honored, unclosed blocks extend to
# the parent terminator or EOF) -- a regex block finder would be a second,
# disagreeing parser.  Benign integration-point content survives.
_EXTENT_TERMINATORS = {"foreignobject": "svg", "annotation-xml": "math"}
_IP_NAMES = ("foreignobject", "annotation-xml")

# SMIL animation elements are "scriptable SVG"; when attributeName targets an
# event handler or href, the whole element is removed (seed/test semantics).
SMIL_ELEMS = frozenset(["set", "animate", "animatetransform", "animatemotion"])


# ---------------------------------------------------------------------------
# per-element attribute / child filtering (shared rule set)
# ---------------------------------------------------------------------------
def _filter_attrs(attrs, set_attr, del_attr, depth=0):
    """Apply the attribute rules to a mapping `attrs` (name -> value),
    using set_attr(name, value) / del_attr(name) to mutate the tree.
    Returns True if anything was removed/changed."""
    changed = False
    drop = []
    for name, value in list(attrs.items()):
        local = name
        if isinstance(local, str):
            idx = local.rfind("}")
            if idx >= 0:
                local = local[idx + 1:]
            # foreign/legacy attributes may carry an XML-style prefix
            # (xlink:href); the dangerous ones are identified by local name
            idx = local.rfind(":")
            if idx >= 0:
                local = local[idx + 1:]
        low = local.lower()
        if low == "srcdoc":
            if depth >= SRCDOC_MAX_DEPTH:
                # beyond the recursion budget: sanitize conservatively by
                # removing the attribute (iframe becomes inert about:blank)
                # instead of recursing until the stack dies
                drop.append(name)
                changed = True
                continue
            cleaned = sanitize_text(value, depth + 1)
            if cleaned != value:
                set_attr(name, cleaned)
                changed = True
            continue
        if low == "style":
            # any executable CSS -> remove the whole attribute (seed/test
            # semantics: dangerous styles are removed, safe styles kept)
            if _css_spans(value):
                drop.append(name)
                changed = True
            continue
        if _ON_ATTR_RE.match(low):
            drop.append(name)
            continue
        if low in URL_ATTRS:
            if _dangerous_url_value(value) is not None:
                drop.append(name)
                changed = True
            continue
        if low == "srcset":
            probe = _unpercent(_CTRL_STRIP.sub("", value))
            if _SRC_SET_DANGER.search(probe):
                drop.append(name)
                changed = True
            continue
        if low == "attributename":
            if _ANIM_ATTR_DANGER.search(value):
                drop.append(name)
                changed = True
                for companion in ("values", "to", "from", "begin", "end"):
                    ck = next(
                        (k for k in attrs if str(k).lower().endswith(companion)),
                        None,
                    )
                    if ck is not None:
                        drop.append(ck)
            continue
    for name in drop:
        if name in attrs:
            del_attr(name)
    return changed


# ---------------------------------------------------------------------------
# html5lib (ElementTree) implementation
# ---------------------------------------------------------------------------
def _localname(tag):
    if not isinstance(tag, str):
        return None
    idx = tag.rfind("}")
    return tag[idx + 1:] if idx >= 0 else tag


def _parse_doc(text):
    p = html5lib.HTMLParser(tree=html5lib.getTreeBuilder("etree"))
    return p.parse(text)


def _parse_frag(text, container="div"):
    p = html5lib.HTMLParser(tree=html5lib.getTreeBuilder("etree"))
    return p.parseFragment(text, container=container)


def _serialize(container, full_doc):
    ser = _HTMLSerializer(omit_optional_tags=False)
    w = getTreeWalker("etree")
    if full_doc:
        return "".join(ser.serialize(w(container)))
    parts = []
    for child in list(container):
        parts.append("".join(ser.serialize(w(child))))
    return "".join(parts)


def _sanitize_tree(root, full_doc, depth=0):
    """Walk the ElementTree iteratively, remove/fix dangerous nodes.
    Returns the new serialized string if any change was made, else None.
    Raises on any unexpected failure -- callers must never alias an
    exception with 'no change' (that would return the unsanitized input)."""
    changed = False
    doomed = set()  # id(element) of elements a parent must remove

    def mark(el):
        doomed.add(id(el))

    stack = [(root, False)]
    while stack:
        el, collect = stack.pop()
        if collect:
            for child in list(el):
                if id(child) in doomed:
                    el.remove(child)
                    changed = True
            continue
        tag = el.tag
        name = _localname(tag)
        if name is None:
            continue  # comment / processing instruction node
        lname = name.lower()
        if lname == "script":
            mark(el)
            continue
        if lname == "style" and el.text:
            if _css_spans(el.text):
                mark(el)  # whole <style> element is the danger carrier
                continue
        if lname == "meta":
            attrs = el.attrib
            he = attrs.get("http-equiv", "")
            if str(he).lower() == "refresh" and "content" in attrs:
                if _meta_refresh_dangerous(attrs["content"]):
                    mark(el)  # whole meta element (navigation carrier)
                    continue
        if lname in SMIL_ELEMS:
            aname = None
            for k, v in el.attrib.items():
                if _attr_local(k).lower() == "attributename":
                    aname = v
                    break
            if aname is not None and _ANIM_ATTR_DANGER.search(aname):
                mark(el)  # whole SMIL element is the scriptable carrier
                continue

        def set_attr(n, v):
            nonlocal changed
            el.attrib[n] = v
            changed = True

        def del_attr(n):
            nonlocal changed
            if n in el.attrib:
                del el.attrib[n]
                changed = True

        if _filter_attrs(el.attrib, set_attr, del_attr, depth):
            changed = True

        stack.append((el, True))
        for child in reversed(list(el)):
            stack.append((child, False))

    if id(root) in doomed:  # unreachable in practice (containers are never
        return ""           # script/meta/style), but never output danger
    out = _serialize(root, full_doc)
    return out if changed else None


# ---------------------------------------------------------------------------
# document-level helpers
# ---------------------------------------------------------------------------
_FULL_DOC_RE = re.compile(
    r"(?is)<!(?:doctype)[^>]*>|<html[\s/>]|<head[\s/>]|<body[\s/>]"
)
_DOCTYPE_RE = re.compile(r"(?is)^([\ufeff\s]*<!doctype[^>]*>)")


def _is_full_doc(text):
    return bool(_FULL_DOC_RE.search(text))


def _attr_local(name):
    local = name
    if isinstance(local, str):
        idx = local.rfind("}")
        if idx >= 0:
            local = local[idx + 1:]
        idx = local.rfind(":")
        if idx >= 0:
            local = local[idx + 1:]
    return local


def _inner_html_dangerous(inner):
    """True if `inner` (raw HTML fragment from inside a <foreignObject>)
    contains dangerous content when interpreted as an HTML DOCUMENT (so a
    <body onload=...> becomes visible and is removed by the sanitizer)."""
    root = _parse_doc(inner)
    return _sanitize_tree(root, True) is not None


def _ip_extents(text, name):
    """Yield (whole_start, whole_end, content_start, content_end, open_tag)
    for every <name> element using TOKENIZER-FAITHFUL extent rules:
    - the start tag is scanned with quote awareness; a self-closing '/>'
      (honored by Chromium for these elements) yields no content;
    - quoted attribute values and <!-- --> comments are opaque while seeking
      the real end tag -- an end tag only closes the element outside them;
    - an unclosed element extends to the parent terminator ('</svg>' for
      foreignObject, '</math>' for annotation-xml) or EOF.
    Semantics stay with the tree walk; this scanner decides only extent."""
    n = len(text)
    start_re = re.compile(r"(?is)<" + name + r"\b")
    i = 0
    while True:
        m = start_re.search(text, i)
        if not m:
            return
        # ---- start tag, quote-aware ----
        j = m.end()
        q = None
        while j < n:
            c = text[j]
            if q:
                if c == q:
                    q = None
            elif c in "\"'":
                q = c
            elif c == ">":
                break
            j += 1
        if j >= n:
            return  # unterminated start tag
        k = j - 1
        while k >= m.end() and text[k] in " \t\r\n\f":
            k -= 1
        self_close = k >= m.end() and text[k] == "/"
        tag_end = j + 1
        open_tag = text[m.start():tag_end]
        if self_close:
            i = tag_end
            continue
        # ---- content: seek the real closer ----
        k = tag_end
        q = None
        closer = None
        while k < n:
            c = text[k]
            if q:
                if c == q:
                    q = None
            elif c in "\"'":
                q = c
            elif text.startswith("<!--", k):
                e = text.find("-->", k + 4)
                k = n if e < 0 else e + 3
                continue
            elif c == "<" and text[k:k + 2].lower() == "</" and \
                    text[k + 2:k + 2 + len(name)].lower() == name:
                nxt = text[k + 2 + len(name):k + 2 + len(name) + 1]
                if nxt in ("", " ", "\t", "\n", "\r", "\f", "/", ">"):
                    closer = k
                    break
            k += 1
        if closer is None:
            term = "</" + _EXTENT_TERMINATORS.get(name, "svg").lower()
            e = text.lower().find(term, tag_end)
            end = e if e >= 0 else n
            yield (m.start(), end, tag_end, end, open_tag)
            return
        e = text.find(">", closer)
        closer_end = e + 1 if e >= 0 else n
        yield (m.start(), closer_end, tag_end, closer, open_tag)
        i = closer_end


def _integration_point_danger_pass(text):
    """Remove <foreignObject>/<annotation-xml(encoding=text/html)> blocks
    whose raw inner content is dangerous when parsed as an HTML document.
    Extents are tokenizer-faithful (_ip_extents); semantics reuse the tree
    walk via _inner_html_dangerous."""
    spans = []
    for name in _IP_NAMES:
        for (ws, we, cs, ce, open_tag) in _ip_extents(text, name):
            # annotation-xml: Chromium fires <body onload> inside it for ANY
            # encoding value (verified) -> treat every block as a candidate;
            # benign MathML/XML content passes the danger check anyway
            inner = text[cs:ce]
            if _inner_html_dangerous(inner):
                spans.append((ws, we))
    if not spans:
        return text
    spans.sort()
    parts = []
    last = 0
    for s, e in spans:
        if s < last:
            continue  # nested span covered by an outer span decided already
        parts.append(text[last:s])
        last = e
    parts.append(text[last:])
    return "".join(parts)


def _mask_integration_spans(text):
    """Mask integration-point spans (equal length) so '<body' inside a
    BENIGN foreignObject/annotation-xml block does not flip fragment inputs
    into full-document mode in _is_full_doc."""
    masked = text
    for name in _IP_NAMES:
        for (ws, we, cs, ce, open_tag) in _ip_extents(masked, name):
            masked = masked[:ws] + "X" * (we - ws) + masked[we:]
    return masked


def _harden_noscript(out):
    """If a <noscript> region's serialized inner content would contain an
    early '</noscript' (so a scripting-enabled browser would end the raw-text
    region early and promote remaining characters to markup), escape every '<'
    inside the region.  This neutralizes the classic noscript mutation XSS
    without touching ordinary noscript content."""
    markers = []
    for m in re.finditer(r"(?is)<noscript\b[^>]*>|</noscript\s*>", out):
        tok = m.group(0)
        markers.append((m.start(), m.end(), tok[1:2] != "/"))
    if not markers:
        return out
    regions = []
    for i, (s, e, is_open) in enumerate(markers):
        if not is_open:
            continue
        region_end = len(out)
        last_close_start = e
        for j in range(i + 1, len(markers)):
            if markers[j][2]:
                region_end = markers[j][0]
                break
            last_close_start = markers[j][0]
        regions.append((e, last_close_start))
    out_low = out.lower()
    for a, b in reversed(regions):
        if "</noscript" in out_low[a:b]:
            out = out[:a] + out[a:b].replace("<", "&lt;") + out[b:]
    return out


_HAS_NOSCRIPT = re.compile(r"(?is)<noscript\b")


def _hardened_noscript_fallback(out):
    if not _HAS_NOSCRIPT.search(out):
        return out
    return _harden_noscript(out)


# ---------------------------------------------------------------------------
# main pipeline
# ---------------------------------------------------------------------------
def sanitize_text(text, depth=0):
    """Sanitize an HTML string; returns the sanitized string.
    Any unexpected failure RAISES: callers must never return input bytes
    on exception -- that would hand back the fully dangerous document."""
    if not _HAS_HTML5LIB:
        raise SanitizerUnavailableError(
            "html5lib is required (vendor it next to filter.py with "
            "'pip install --target=vendor html5lib'); refusing to sanitize "
            "with a weaker parser"
        )
    text = _integration_point_danger_pass(text)
    full = _is_full_doc(_mask_integration_spans(text))
    doctype_m = _DOCTYPE_RE.match(text)
    doctype = doctype_m.group(1) if doctype_m else None
    # Fragments containing <frameset>/<frame> are parsed in a frameset
    # fragment context: a div context drops those tokens, the walk then sees
    # "no change" and the raw (executable) bytes would be returned untouched.
    fs_container = not full and bool(_FRAMESET_RE.search(text))

    cur = text
    for _ in range(4):  # fixpoint loop: re-parse & re-sanitize until stable
        if full:
            root = _parse_doc(cur)
        else:
            root = _parse_frag(cur, container="frameset" if fs_container else "div")
        changed_out = _sanitize_tree(root, full, depth)
        if changed_out is None:
            break
        if changed_out == cur:
            break
        cur = changed_out
    out = cur

    out = _hardened_noscript_fallback(out)

    if text.startswith('\ufeff') and not out.startswith('\ufeff'):
        out = '\ufeff' + out
    if full and doctype:
        low = out.lstrip().lower()
        if not low.startswith("<!doctype"):
            out = doctype + "\n" + out if not out.startswith(doctype) else out
    return out


class SanitizerUnavailableError(RuntimeError):
    """Raised when html5lib cannot be loaded; the file must NOT be touched."""


def filter_file(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:  # pragma: no cover
        text = raw.decode("utf-8", errors="replace")
    out = sanitize_text(text)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("usage: python3 filter.py <html-file>\n")
        return 2
    try:
        filter_file(argv[1])
    except SanitizerUnavailableError as exc:
        sys.stderr.write("filter.py: " + str(exc) + "\n")
        return 3
    except Exception as exc:  # fail closed on ANY abort: file untouched
        sys.stderr.write(
            "filter.py: sanitization aborted; input file left untouched: "
            + repr(exc) + "\n"
        )
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))