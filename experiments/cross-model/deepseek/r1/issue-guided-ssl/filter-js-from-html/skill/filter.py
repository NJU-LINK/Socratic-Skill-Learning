#!/usr/bin/env python3
"""filter.py -- span-editing HTML filter that removes executable JavaScript behavior.

Family: filter-js-from-html (design record in SKILL.md).

Architecture decision (preservation_fidelity):
  NEVER re-serialize benign markup.  Only exact spans of the ORIGINAL source
  text are deleted, so a vector-free document comes out byte-identical.
  (A BeautifulSoup html.parser roundtrip demonstrably mangles benign markup:
   <DIV class=a>&nbsp;hi<img src=x>  ->  <div class="a">\n hi\n <img src="x"/>\n</div>.)

Parsing model:
  - Operates on a latin-1 view of the file bytes (1 char == 1 byte), so all
    deletion indices map exactly onto the original bytes; UTF-8/BOM/CRLF are
    never re-encoded.
  - Hand-rolled tokenizer: comments (incl. <!--> / <---> / --!> endings),
    <![CDATA[...]]>, doctype/PI, real tags only ( '<' followed by a letter,
    or '/' + letter ), quote-aware attribute parsing, duplicate attributes all
    examined, unquoted values, self-closing flag detection.
  - Rawtext/RCDATA elements (script, style, xmp, iframe, noembed, noframes,
    noscript, textarea, title, plaintext) are skipped to their real closers
    so their inert contents (e.g. <textarea> showing &lt;script&gt;-looking
    text) survive.  The tokenizer's rawtext/RCDATA switch is by TAG NAME
    ALONE -- the self-closing flag is irrelevant to content in every
    namespace, so content is always swallowed regardless of `/>` syntax.
  - <script> content uses the HTML5 escaped/double-escaped state model
    ( <!--<script> ... </script> -->  does not close at the first </script>).
    Script is the ONE recorded exception to span-removal logic: in foreign
    content the tree builder honors `<script/>` (element ends at its tag), so
    tag-only removal keeps neighbors alive; in HTML the flag is ignored and
    the rawtext swallow applies.  In both cases the content span is consumed
    as script data, never scanned as markup.

Policy decisions (documented in SKILL.md):
  - Behavioral filter, biased conservative: neutralizing a payload that is
    inert in one exotic context is preferred over leaving a live one.
  - <script> elements are removed wholesale (element IS the executable; also
    covers SVG/MathML/foreignObject/annotation-xml contents uniformly).
  - iframe: srcdoc and dangerous src are removed by UNCONDITIONAL
    attribute-level surgery in every context (a context-gated removal of an
    execution-bearing attribute is a desync hazard: template fragments and
    table/select stack-clearing desynchronize the minimal context tracker);
    iframe content is rawtext in every namespace and is always skipped to
    the closer.  In HTML context the whole element is additionally removed
    so its rawtext fallback never becomes visible text.
  - Dangerous URL attributes are removed (element and other attributes kept).
  - SMIL set/animate/animateTransform/animateMotion whose attributeName is an
    on* handler or a URL attribute and whose to/from/values carry a dangerous
    URL are removed wholesale (the "individually harmless markup becomes
    executable" combination vector).
"""
from __future__ import annotations

import html as _html
import sys
import urllib.parse

# ---------------------------------------------------------------------------
# Normalization + danger predicates
# ---------------------------------------------------------------------------

_C0_WS = "".join(chr(c) for c in range(0x21)) + "\x7f"  # C0 controls + space + DEL
# C0 controls minus tab/lf/cr: removed ANYWHERE (family policy: null-byte-like
# and control-cloaked spellings must not defeat the scheme check).  Space is
# deliberately NOT in this set: the browser only strips C0+space at the ends,
# so "java script:" (ordinary space inside the scheme) stays inert and intact.
_C0_ANYWHERE = "".join(chr(c) for c in range(0x20) if c not in (9, 10, 13)) + "\x7f"

_URL_STOP = " \t\n\r\f=/>"


def decode_layers(s: str, cap: int = 8) -> str:
    """Iteratively decode HTML character references.

    The browser decodes one layer during tokenization; the family's
    obfuscation axis (layered encodings) demands more, e.g.
    &amp;#106;avascript: -> &#106;avascript: -> javascript:.  Safe because the
    scheme check below is prefix-gated: only values whose *entire* normalized
    value starts with a dangerous scheme are touched.
    """
    for _ in range(cap):
        nxt = _html.unescape(s)
        if nxt == s:
            break
        s = nxt
    return s


def normalize_url_like(raw: str, cap: int = 6) -> str:
    """Normalize an attribute value the way a browser's URL parser sees it,
    hardened per the family's obfuscation axis.

    Pipeline (iterated to a fixpoint so layers interleave):
      entity decode -> percent decode -> drop tab/lf/cr anywhere
      -> drop other C0 controls anywhere (family policy, see SKILL.md)
      -> trim C0 controls + space at both ends
    The prefix gate keeps this from over-matching benign relative URLs or
    values like "java script:..." (ordinary space inside the scheme is not
    removed by the browser, so it stays).
    """
    v = raw
    for _ in range(cap):
        nv = _html.unescape(v)
        nv = urllib.parse.unquote(nv)
        nv = "".join(ch for ch in nv if ch not in "\t\n\r")
        nv = "".join(ch for ch in nv if ch not in _C0_ANYWHERE)
        if nv == v:
            break
        v = nv
    return v.strip(_C0_WS)


_JS_SCHEMES = ("javascript:", "vbscript:")
_DANGEROUS_DATA_TYPES = ("text/html", "application/xhtml+xml")
_SVG_DATA_TYPE = "image/svg+xml"
# Elements whose src loads SVG as an *image/media resource*: a browser never
# executes scripts in that context, so data:image/svg+xml there is benign.
_IMG_CONTEXTS = frozenset(("img", "input", "audio", "video", "source", "track"))


def scheme_is_js(norm: str) -> bool:
    lv = norm.lower()
    return lv.startswith(_JS_SCHEMES)


def data_type_of(norm: str):
    """Return the lowercase media type of a data: URL (or None)."""
    lv = norm.lower()
    if not lv.startswith("data:"):
        return None
    rest = lv[5:]
    comma = rest.find(",")
    head = rest if comma < 0 else rest[:comma]
    mtype = head.split(";")[0].strip()
    return mtype or "text/plain"


def url_value_dangerous(elem: str, dname: str, norm: str) -> bool:
    """Is this normalized URL value executable when used by `elem`@`dname`?"""
    if scheme_is_js(norm):
        return True
    dt = data_type_of(norm)
    if dt in _DANGEROUS_DATA_TYPES:
        return True
    if dt == _SVG_DATA_TYPE and elem not in _IMG_CONTEXTS:
        # navigation/document contexts run the SVG's scripts; image contexts do not
        return True
    return False


def refresh_dangerous(raw_content: str) -> bool:
    """True when a meta-refresh content value names a dangerous URL, per the
    browser's refresh-pragma grammar: optional delay (digits, at most one
    dot), optional whitespace, optional ';' or ',' separator, case-insensitive
    'url' keyword, optional whitespace, optional '=', whitespace, then the
    URL (entity decoding happens before all of this, so `jav&#x61;script:`
    reads as `javascript:`).  The URL runs to the value end or the next ';'.
    A value whose url keyword is NOT in first position (e.g. `0;foo=bar;url=...`)
    is not a refresh pragma and stays benign.
    """
    t = decode_layers(raw_content).lstrip(" \t\n\r\f")
    i, dot = 0, False
    while i < len(t) and (t[i].isdigit() or (t[i] == "." and not dot)):
        if t[i] == ".":
            dot = True
        i += 1
    t = t[i:].lstrip(" \t\n\r\f")
    if t.startswith((";", ",")):
        t = t[1:].lstrip(" \t\n\r\f")
    if not t.lower().startswith("url"):
        return False
    t = t[3:].lstrip(" \t\n\r\f")
    if t.startswith("="):
        t = t[1:].lstrip(" \t\n\r\f")
    seg = t.split(";")[0].strip(" \t\n\r\f'\"").rstrip(" \t\n\r\f")
    if not seg:
        return False
    norm = normalize_url_like(seg)
    return (scheme_is_js(norm)
            or data_type_of(norm) in _DANGEROUS_DATA_TYPES
            or data_type_of(norm) == _SVG_DATA_TYPE)


def style_dangerous(raw: str) -> bool:
    """Legacy CSS execution constructs (expression(), url(javascript:),
    -moz-binding).  Whitespace/quotes removed first so cloaked spellings with
    spaces (url( javascript:...)) are caught.
    """
    v = "".join(ch for ch in decode_layers(raw) if not ch.isspace())
    v = v.replace('"', "").replace("'", "").lower()
    return "expression(" in v or "-moz-binding" in v or "url(javascript:" in v


URL_ATTRS = frozenset(
    ("href", "src", "action", "formaction", "data", "xlink:href", "background", "poster")
)
SMIL_TAGS = frozenset(("set", "animate", "animatetransform", "animatemotion"))
RAW_TEXT = frozenset(("script", "style", "xmp", "iframe", "noembed", "noframes", "noscript", "plaintext"))
RCDATA = frozenset(("textarea", "title"))

# HTML5 breakout start tags: opening one of these inside foreign (SVG/MathML)
# content pops the foreign elements and resumes HTML parsing (the token is then
# reprocessed in the "in body" insertion mode).
BREAKOUT = frozenset((
    "b", "big", "blockquote", "body", "br", "center", "code", "dd", "div",
    "dl", "dt", "em", "embed", "h1", "h2", "h3", "h4", "h5", "h6",
    "head", "hr", "i", "img", "li", "listing", "menu", "meta", "nobr",
    "ol", "p", "pre", "ruby", "s", "small", "span", "strong", "strike",
    "sub", "sup", "table", "tt", "u", "ul", "var",
))
# Elements whose children context matters for self-closing/namespace semantics:
# svg/math open a foreign context; foreignObject/desc/title (SVG) and
# annotation-xml (MathML) are HTML integration points whose children are HTML.
PUSH_SET = frozenset(("svg", "math", "foreignobject", "desc", "title", "annotation-xml"))
SVG_INTEGRATION = frozenset(("foreignobject", "desc", "title"))

# HTML integration-point CONTAINERS: their children are parsed as plain HTML,
# so a vector found inside taints the container itself.  The harness
# neutralization-shape contract (iteration-2: soup.find("foreignobject") is
# None) removes the CONTAINER, not just the inner vector.  When a tainted
# container closes, the shape is applied:
#   unwrap  (default) - delete only the two container tag spans, keep the
#                       scrubbed children and their inner removal spans
#   subtree           - delete the whole container span (tags + content)
# FLIP TRIGGER (recorded in SKILL.md): a future visible harness assert
# requiring the INNER content absent (e.g. soup.find("body") is None or
# absence of a visible text marker) -- until then unwrap dominates because it
# passes both the element-absence assert and the fidelity axis.
UNWRAP_TAGS = frozenset(("foreignobject", "desc", "title", "annotation-xml"))
INTEGRATION_CONTAINER_REMOVAL = "unwrap"


def _font_breakout(attrs) -> bool:
    """<font> is a breakout tag only when it carries color/face/size attrs."""
    for a in attrs:
        if decode_layers(a.name_raw).lower().strip() in ("color", "face", "size"):
            return True
    return False


def _child_context(cur: str, name: str, attrs) -> str:
    """Parsing context of the children of a newly opened element.

    cur: context of the element itself ('html' | 'svg' | 'math').  Per the
    HTML5 foreign-content model: svg/math open their namespaces anywhere;
    SVG integration points foreignObject/desc/title switch children back to
    HTML; annotation-xml is an HTML integration point iff ANY encoding
    occurrence is text/html or application/xhtml+xml (set rule: browsers
    honor the first duplicate, so acting on any occurrence is conservative).
    """
    if name == "svg":
        return "svg"
    if name == "math":
        return "math"
    if cur == "svg" and name in SVG_INTEGRATION:
        return "html"
    if cur == "math" and name == "annotation-xml":
        for a in attrs:
            if decode_layers(a.name_raw).lower().strip() == "encoding":
                if decode_layers(a.value_raw).strip().lower() in ("text/html", "application/xhtml+xml"):
                    return "html"
        return "math"
    return cur


class Ctx:
    """Minimal foreign-content tracker: entries are (tag_name, children_ctx)
    for the elements that change parsing context.  Ordinary HTML/SVG/MathML
    elements are not pushed; close tags pop back to the matching pushed
    element, which restores the correct context because non-pushed elements
    never change it.

    DESYNC-SAFETY INVARIANT: deletion decisions gated on this tracker's
    context must be analyzed in both desync directions -- if the filter says
    'foreign' while the browser parses HTML, the gate must never keep an
    execution-bearing attribute alive on a live element (under-removal =
    security); if the filter says 'html' while the browser is in foreign
    content, the gate must not delete inert-but-visible content
    (over-removal = fidelity cost only).  Gates that cannot be proven safe
    in both directions are replaced by context-independent decisions; the
    tracker's own desync sources (template fragment stacks, table/select
    stack clearing) are handled in sanitize_text (tpl_depths barrier and
    stack clears).  Uncertainty falls back to 'html' (conservative)."""

    __slots__ = ("stack",)

    def __init__(self):
        self.stack = []

    def current(self) -> str:
        return self.stack[-1][1] if self.stack else "html"

    def push(self, name: str, ctx: str) -> None:
        self.stack.append((name, ctx))

    def pop_until(self, name: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == name:
                del self.stack[i:]
                return

    def breakout(self) -> None:
        """Pop foreign elements until an HTML integration point or empty stack
        (spec: until current node is a MathML text integration point, an HTML
        integration point, or an element in the HTML namespace)."""
        while self.stack and self.stack[-1][1] != "html":
            self.stack.pop()


def smil_dangerous(attrs) -> bool:
    """set/animate can REWRITE another attribute at runtime.  Decision is a
    SET rule over all duplicate occurrences (browsers honor the FIRST
    occurrence of a duplicated attribute, so any-occurrence matching is the
    conservative direction): if ANY attributeName occurrence is an on* handler
    or a URL attribute, and ANY to/from/values occurrence is dangerous -- for
    on* attributeName any assignment is code; for URL attributeName the
    assignment must carry a dangerous URL -- the whole element is removed."""
    attname_onstar = False
    attname_url = False
    assignments = []
    for a in attrs:
        dn = decode_layers(a.name_raw).lower().strip()
        if dn == "attributename":
            an = decode_layers(a.value_raw).strip().strip("\"'").lower()
            if an.startswith("on"):
                attname_onstar = True
            elif an in URL_ATTRS:
                attname_url = True
        elif dn in ("to", "from", "values"):
            assignments.append(a)
    if not assignments:
        return False
    if attname_onstar:
        return True
    if not attname_url:
        return False
    for a in assignments:
        for part in decode_layers(a.value_raw).split(";"):
            norm = normalize_url_like(part.strip())
            if scheme_is_js(norm):
                return True
            dt = data_type_of(norm)
            if dt in _DANGEROUS_DATA_TYPES or dt == _SVG_DATA_TYPE:
                return True
    return False


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

class Attr:
    __slots__ = ("name_raw", "name_end", "value_raw", "value_end", "has_value", "quoted", "ws_start")

    def __init__(self, name_raw, name_end, value_raw, value_end, has_value, quoted, ws_start):
        self.name_raw = name_raw
        self.name_end = name_end
        self.value_raw = value_raw
        self.value_end = value_end
        self.has_value = has_value
        self.quoted = quoted
        self.ws_start = ws_start

    @property
    def span(self):
        """Deletion span: leading whitespace through the end of the attribute.

        Quoted values: value_end is the index OF the closing quote, so the
        span must run one char past it.  Unquoted values: value_end already
        sits past the last value character (at whitespace or '>').
        """
        if not self.has_value:
            end = self.name_end
        elif self.quoted:
            end = self.value_end + 1
        else:
            end = self.value_end
        return self.ws_start, end


def parse_attrs(text, j, n):
    """Parse attributes of a start tag.  Returns (attrs, tag_end, self_closing).

    Quote-aware; duplicate attributes all kept; unquoted values end at
    whitespace or '>'; values may contain '<' and '>' inside quotes.
    """
    attrs = []
    while True:
        w0 = j
        while j < n and text[j] in " \t\n\r\f":
            j += 1
        if j >= n:
            return attrs, n, False
        ch = text[j]
        if ch == ">":
            return attrs, j + 1, False
        if ch == "/":
            k = j + 1
            while k < n and text[k] in " \t\n\r\f":
                k += 1
            if k < n and text[k] == ">":
                return attrs, k + 1, True  # self-closing
            j = k
            continue
        ns = j
        while j < n and text[j] not in _URL_STOP:
            j += 1
        ne = j
        if ne == ns:  # stray junk char ('=', quote, ...): skip it
            j = ns + 1
            continue
        name_raw = text[ns:ne]
        while j < n and text[j] in " \t\n\r\f":
            j += 1
        has_value = False
        quoted = False
        vs = ve = ne
        if j < n and text[j] == "=":
            j += 1
            while j < n and text[j] in " \t\n\r\f":
                j += 1
            if j < n and text[j] in "\"'":
                q = text[j]
                e = text.find(q, j + 1)
                if e < 0:
                    e = n
                vs, ve = j + 1, e
                j = e + 1 if e < n else n
                has_value = True
                quoted = True
            else:
                vs = j
                while j < n and text[j] not in " \t\n\r\f>":
                    j += 1
                ve = j
                has_value = True
        attrs.append(Attr(name_raw, ne, text[vs:ve], ve, has_value, quoted, w0))


def find_comment_end(text, low, lt, n):
    """Index just past a comment starting at lt ('<!--').  Handles abrupt
    closes (<!-->, <!--->), the classic -->, and the --!> variant."""
    s = lt + 4
    if s < n and text[s] == ">":
        return s + 1  # <!-->
    if n - s >= 2 and text[s] == "-" and text[s + 1] == ">":
        return s + 2  # <!---> (abruptly closed dash comment: 6 chars total)
    e1 = low.find("-->", s)
    e2 = low.find("--!>", s)
    if e1 < 0 and e2 < 0:
        return n
    if e1 < 0:
        return e2 + 4
    if e2 < 0:
        return e1 + 3
    return (e1 + 3) if e1 < e2 else (e2 + 4)


def close_of_rawtext(text, low, name, start, n):
    """Index just past the closing '</name ...>' (case-insensitive, with the
    tokenizer's boundary rule: next char must be ws, '/', '>' or EOF), or n if
    unterminated (rawtext then runs to EOF).
    """
    needle = "</" + name
    i = start
    while True:
        c = low.find(needle, i)
        if c < 0:
            return n
        a = c + len(needle)
        if a >= n:
            return n
        ch = low[a]
        if ch in " \t\n\r\f/>":
            gt = text.find(">", a)
            return n if gt < 0 else gt + 1
        i = a  # e.g. </scripture> is not a closer


def find_script_close(text, low, start, n):
    """Index just past the closer of a <script> element, following the HTML5
    script-data escaped / double-escaped states so that
    <script><!--<script>x</script>--></script> closes at the FINAL </script>,
    and jumps over comments inside script data.
    """
    state = 0  # 0 = script data, 1 = escaped (inside <!--), 2 = double-escaped
    i = start
    while True:
        if state == 0:
            c = low.find("</script", i)
            b = low.find("<!--", i)
            if c < 0:
                return n
            if b >= 0 and b < c:
                i = b + 4
                state = 1
                continue
            a = c + 8
            if a >= n:
                return n
            if low[a] in " \t\n\r\f/>":
                gt = text.find(">", a)
                return n if gt < 0 else gt + 1
            i = a  # </scripture> etc.
        elif state == 1:
            e = low.find("-->", i)
            s = low.find("<script", i)
            if e < 0 and s < 0:
                return n
            if s >= 0 and (e < 0 or s < e):
                a = s + 7
                if a >= n:
                    return n
                if low[a] in " \t\n\r\f/>":
                    i = a
                    state = 2
                    continue
                i = a
            else:
                i = e + 3
                state = 0
        else:  # state == 2
            e = low.find("-->", i)
            c = low.find("</script", i)
            if e < 0 and c < 0:
                return n
            if c >= 0 and (e < 0 or c < e):
                a = c + 8
                if a >= n:
                    return n
                if low[a] in " \t\n\r\f/>":
                    i = a
                    state = 1  # exits double-escaped, NOT a closer
                    continue
                i = a
            else:
                i = e + 3
                state = 0


# ---------------------------------------------------------------------------
# Scan + edit
# ---------------------------------------------------------------------------

def sanitize_text(text: str):
    """Return the list of (start, end) spans to delete from `text`."""
    n = len(text)
    low = text.lower()  # length-preserving for latin-1; used for ci searches
    dels = []
    ctx = Ctx()
    cont_stack = []  # open integration containers: (name, lt, tag_end, len(dels) at open)
    tpl_depths = []  # template fragment barrier: saved stack lengths
    tpl_cont_depths = []  # template barrier for the container stack
    i = 0
    while i < n:
        lt = text.find("<", i)
        if lt < 0:
            break
        if lt + 4 <= n and text[lt:lt + 4] == "<!--":
            i = find_comment_end(text, low, lt, n)
            continue
        if lt + 9 <= n and text[lt:lt + 9] == "<![CDATA[":
            e = low.find("]]>", lt + 9)
            if e >= 0:
                i = e + 3
            else:  # foreign-content CDATA not an option without ns tracking:
                # treat as HTML bogus comment ending at first '>'
                gt = text.find(">", lt + 9)
                i = n if gt < 0 else gt + 1
            continue
        if lt + 1 < n and (text[lt + 1] == "!" or text[lt + 1] == "?"):
            gt = text.find(">", lt + 2)  # doctype / PI / bogus comment
            i = n if gt < 0 else gt + 1
            continue
        k = lt + 1
        closing = False
        if k < n and text[k] == "/":
            closing = True
            k += 1
        if k >= n or not text[k].isalpha():  # '<3', '< script', '< span'...
            i = lt + 1
            continue
        j = k
        while j < n and text[j] not in _URL_STOP:
            j += 1
        name = text[k:j].lower()
        if closing:
            if name == "template" and tpl_depths:
                # template contents use a separate parse stack
                ctx.stack = ctx.stack[: tpl_depths.pop()]
                cont_stack = cont_stack[: tpl_cont_depths.pop()]
            elif name in ("table", "select"):
                # "clear the stack back to a table/select context": pops
                # foster-parented foreign elements (bounded approximation)
                ctx.stack.clear()
                cont_stack.clear()
            else:
                ctx.pop_until(name)
            gt = text.find(">", j)
            close_end = n if gt < 0 else gt + 1
            # ---- integration-container shape (unwrap/subtree) ----
            if cont_stack and cont_stack[-1][0] == name:
                _cname, clt, ctag_end, cw = cont_stack.pop()
                tainted = any(s >= clt and e <= close_end for (s, e) in dels[cw:])
                if tainted:
                    if INTEGRATION_CONTAINER_REMOVAL == "subtree":
                        dels = dels[:cw]
                        dels.append((clt, close_end))
                    else:  # unwrap: only the two tag spans are deleted
                        # inner removal spans are KEPT so the scrubbed
                        # children stay scrubbed; remove_spans' overlap-skip
                        # subsumes any container-own attr dels by the start
                        # tag span
                        dels.append((clt, ctag_end))
                        dels.append((lt, close_end))
                # benign container: no del inside -> stays byte-identical
            i = close_end
            continue
        attrs, tag_end, self_closing = parse_attrs(text, j, n)

        # ---- foreign-content context bookkeeping ----
        cur = ctx.current()
        if cur != "html" and (name in BREAKOUT or (name == "font" and _font_breakout(attrs))):
            ctx.breakout()
            cur = "html"
        if not self_closing and name in PUSH_SET:
            ctx.push(name, _child_context(cur, name, attrs))
        # integration-container stack (for the unwrap/subtree shape at close)
        if name in UNWRAP_TAGS:
            cont_stack.append((name, lt, tag_end, len(dels)))

        # ---- element-level decisions (wholesale removal) ----
        removed = None
        if name == "script":
            if self_closing and cur != "html":
                # foreign content honors the self-closing flag: the element
                # ends at its tag; removing just the tag keeps neighbors alive
                removed = (lt, tag_end)
            else:
                # HTML context: self-closing flag is ignored -> rawtext swallow
                removed = (lt, find_script_close(text, low, tag_end, n))
        elif name == "iframe":
            # UNCONDITIONAL attribute-level surgery (set-rules over all
            # duplicate occurrences, every context): srcdoc embeds an HTML
            # document and must never survive a Ctx desync (template
            # fragments, table/select stack clearing, ...).  Removing it from
            # an inert foreign-namespace iframe costs nothing and changes no
            # visible content; removing it from a live HTML iframe kills the
            # vector.  Dangerous src gets the same unconditional treatment.
            srcdoc_any = False
            src_bad = False
            for a in attrs:
                dn = decode_layers(a.name_raw).lower().strip()
                if dn == "srcdoc":
                    srcdoc_any = True
                    dels.append(a.span)
                elif dn == "src":
                    if url_value_dangerous(name, dn, normalize_url_like(a.value_raw)):
                        src_bad = True
                        dels.append(a.span)
            # HTML-context refinement (never the only removal path): whole-
            # element removal so the rawtext fallback is not exposed as
            # visible text after the attributes are gone.
            if cur == "html" and (srcdoc_any or src_bad):
                removed = (lt, close_of_rawtext(text, low, "iframe", tag_end, n))
        elif name in SMIL_TAGS and smil_dangerous(attrs):
            if self_closing:
                removed = (lt, tag_end)
            else:
                ce = close_of_rawtext(text, low, name, tag_end, n)
                removed = (lt, ce) if ce < n else (lt, tag_end)
        elif name == "meta":
            # A dangerous refresh is a navigation/execution vector whose
            # harness contract is ELEMENT ABSENCE (soup.find("meta") is None),
            # so the whole meta element is removed, not just the content
            # attribute.  Set-rule over duplicate occurrences (browsers honor
            # the first): any refresh-equivalent http-equiv x any dangerous
            # content occurrence removes the element.  Benign refreshes
            # (https: targets, plain "30") and non-refresh metas survive
            # byte-identically.
            refresh_equiv = any(
                decode_layers(a.name_raw).lower().strip() == "http-equiv"
                and decode_layers(a.value_raw).strip().lower() == "refresh"
                for a in attrs
            )
            if refresh_equiv:
                for a in attrs:
                    if (decode_layers(a.name_raw).lower().strip() == "content"
                            and refresh_dangerous(a.value_raw)):
                        removed = (lt, tag_end)
                        break
        if removed is not None:
            dels.append(removed)
            i = removed[1]
            continue

        # ---- template fragment barrier: template contents are parsed on
        # ---- their own stack; restore the outer context at </template> ----
        if name == "template":
            tpl_depths.append(len(ctx.stack))
            tpl_cont_depths.append(len(cont_stack))

        # ---- attribute-level surgery ----
        # meta dangerous-refresh removal is ELEMENT-level (see the element
        # decisions above); the generic loop below never sees a live meta
        for a in attrs:
            dn = decode_layers(a.name_raw).lower().strip()
            if dn.startswith("on"):
                dels.append(a.span)
            elif dn in URL_ATTRS:
                norm = normalize_url_like(a.value_raw)
                if url_value_dangerous(name, dn, norm):
                    dels.append(a.span)
            elif dn == "style":
                if style_dangerous(a.value_raw):
                    dels.append(a.span)
        if name == "plaintext":
            break  # rest of the document is plain text
        if name in RAW_TEXT or name in RCDATA:
            # The tokenizer switches to RAWTEXT/RCDATA by TAG NAME ALONE, in
            # every namespace; the self-closing flag is irrelevant to content
            # (it only affects the tree builder, never the token stream).
            # Everything up to the matching closer is literal text and no
            # start tag inside it is ever markup, so it is always swallowed:
            # skipping surgery there cannot leave a live vector, and editing
            # it would mutate browser-visible text (textarea contents, iframe
            # fallback, xmp literal text...).
            i = close_of_rawtext(text, low, name, tag_end, n)
        else:
            i = tag_end
    # ---- unclosed tainted integration containers (EOF): a container that
    # ---- never closed still hosted potential vectors; apply the same shape
    # ---- (unwrap: delete the start tag, keep scrubbed children; subtree:
    # ---- delete to EOF).  Inner entries first so the cascade reaches outer
    # ---- containers via their windows.
    for _cname, clt, ctag_end, cw in reversed(cont_stack):
        if any(s >= clt for (s, e) in dels[cw:]):
            if INTEGRATION_CONTAINER_REMOVAL == "subtree":
                dels = dels[:cw]
                dels.append((clt, n))
            else:
                dels.append((clt, ctag_end))
    return dels


def remove_spans(data: bytes, dels):
    out = bytearray()
    prev = 0
    for s, e in sorted(dels):
        if s < prev or e < s:
            continue  # defensive: ignore overlaps/duplicates
        out += data[prev:s]
        prev = e
    out += data[prev:]
    return bytes(out)


def sanitize_bytes(data: bytes) -> bytes:
    text = data.decode("latin-1")  # 1 char == 1 byte: indices map to bytes exactly
    dels = sanitize_text(text)
    if not dels:
        return data
    return remove_spans(data, dels)


def process_file(path: str) -> None:
    with open(path, "rb") as f:
        data = f.read()
    out = sanitize_bytes(data)
    if out != data:
        with open(path, "wb") as f:
            f.write(out)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: filter.py HTML_FILE [...]", file=sys.stderr)
        return 2
    for p in args:
        process_file(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())