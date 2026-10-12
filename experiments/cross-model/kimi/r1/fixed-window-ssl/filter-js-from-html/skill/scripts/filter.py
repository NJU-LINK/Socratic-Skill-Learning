#!/usr/bin/env python3
"""Filter JavaScript and executable content from HTML files.
"""
import sys
import re
from html.parser import HTMLParser
from html import escape


# URL attributes that can contain executable content
URL_ATTRS = {'href', 'src', 'action', 'formaction', 'poster', 'xlink:href', 'data'}

# Container elements - drop until matching end tag
DROP_CONTAINERS = {'script', 'iframe', 'object', 'applet', 'frameset', 'frame', 'noframes', 
                    'foreignobject', 'foreignObject', 'annotation-xml'}  # SVG/MathML HTML integration points

# Void elements - drop tag only, no state change
DROP_VOID = {'embed'}

# SVG/MathML animation elements that can be containers when dangerous
ANIMATION_ELEMENTS = {'animate', 'set', 'animatecolor', 'animatetransform', 'animatemotion'}

# Raw text elements
RAW_TEXT_ELEMENTS = {'script', 'style', 'noembed', 'noframes', 'xmp', 'iframe'}

# Elements to preserve verbatim
PRESERVE_RAW = {'style'}


def dangerous_url(value):
    """Check if URL contains executable schemes."""
    if not isinstance(value, str):
        return False
    
    # Strip control chars
    v = value.translate({9: '', 10: '', 13: '', 0: ''})
    v = v.lstrip(' \x00-\x1f')
    v = v.lower()
    
    if v.startswith(('javascript:', 'vbscript:')):
        return True
    
    if v.startswith('data:'):
        med = v[5:].split(',', 1)[0]
        if 'text/html' in med or 'xhtml' in med or 'svg' in med:
            return True
    
    return False


def has_dangerous_css_url(style_value):
    """Check CSS for dangerous url() values."""
    if not isinstance(style_value, str):
        return False
    
    url_pattern = r'url\s*\(\s*["\']?([^\)"\']+)["\']?\s*\)'
    for url in re.findall(url_pattern, style_value, re.I):
        url = url.translate({9: '', 10: '', 13: '', 0: ''}).lstrip(' \x00-\x1f').lower()
        if url.startswith(('javascript:', 'vbscript:')):
            return True
    return False


def is_dangerous_refresh_content(content):
    """Check meta refresh content for dangerous URLs."""
    if not isinstance(content, str):
        return False
    match = re.search(r'url\s*=\s*(.+)', content, re.I)
    if match:
        return dangerous_url(match.group(1).strip().strip('"\''))
    return False


def is_event_handler(name):
    return name.lower().startswith('on')


def is_dangerous_animation_element(tag, attrs):
    """Check if SVG animation element is dangerous."""
    attrs_dict = {n.lower(): v for n, v in attrs}
    
    attr_name = attrs_dict.get('attributename', '').lower()
    if attr_name in ('href', 'xlink:href') or attr_name.startswith('on'):
        return True
    
    for key in ('values', 'to', 'from', 'by'):
        if key in attrs_dict and dangerous_url(attrs_dict[key]):
            return True
    return False


def is_dangerous_meta(attrs):
    attrs_dict = {n.lower(): v for n, v in attrs}
    if attrs_dict.get('http-equiv', '').lower() == 'refresh':
        return is_dangerous_refresh_content(attrs_dict.get('content', ''))
    return False


def has_duplicate_attrs(attrs):
    seen = set()
    for name, _ in attrs:
        n = name.lower()
        if n in seen:
            return True
        seen.add(n)
    return False


class HTMLFilter(HTMLParser):
    def __init__(self, convert_charrefs=False):
        super().__init__(convert_charrefs=convert_charrefs)
        self.output = []
        self.drop_stack = []  # Stack for nested drop regions
        self.preserve_stack = []  # Stack for nested preserve regions
    
    def emit(self, text):
        if not self.drop_stack:
            self.output.append(text)
    
    def _process_attrs(self, tag, attrs):
        seen = set()
        safe_attrs = []
        has_dangerous = False
        
        for name, value in attrs:
            n = name.lower()
            if n in seen:
                continue
            seen.add(n)
            
            if is_event_handler(name):
                has_dangerous = True
                continue
            
            if n in URL_ATTRS or n.startswith('xlink:'):
                if dangerous_url(value):
                    has_dangerous = True
                    continue
            
            if n == 'style' and has_dangerous_css_url(value):
                has_dangerous = True
                continue
            
            if n == 'srcdoc' and value:
                inner = HTMLFilter(convert_charrefs=False)
                inner.feed(value)
                inner.close()
                safe_attrs.append((name, ''.join(inner.output)))
                continue
            
            safe_attrs.append((name, value))
        
        return safe_attrs, has_dangerous
    
    def _emit_starttag(self, tag, attrs, self_closing=False):
        parts = ['<', tag]
        for name, value in attrs:
            if value is not None:
                parts.extend([' ', name, '="', escape(str(value), quote=True), '"'])
            else:
                parts.extend([' ', name])
        parts.append(' />' if self_closing else '>')
        self.emit(''.join(parts))
    
    def _is_drop_container(self, tag, attrs):
        t = tag.lower()
        if t in DROP_CONTAINERS:
            return True
        if t in ANIMATION_ELEMENTS and is_dangerous_animation_element(tag, attrs):
            return True
        return False
    
    def _is_drop_void(self, tag, attrs):
        t = tag.lower()
        if t in DROP_VOID:
            return True
        if t == 'meta' and is_dangerous_meta(attrs):
            return True
        return False
    
    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        
        if self.preserve_stack:
            self.emit(self.get_starttag_text() or f'<{tag}>')
            return
        
        if self._is_drop_void(tag, attrs):
            return
        
        if t in PRESERVE_RAW:
            self.preserve_stack.append(t)
            self.emit(self.get_starttag_text() or f'<{tag}>')
            return
        
        if self._is_drop_container(tag, attrs):
            self.drop_stack.append(t)
            return
        
        safe_attrs, has_dangerous = self._process_attrs(tag, attrs)
        has_dups = has_duplicate_attrs(attrs)
        
        if not has_dangerous and not has_dups:
            raw = self.get_starttag_text()
            if raw:
                self.emit(raw)
                return
        
        self._emit_starttag(tag, safe_attrs)
    
    def handle_startendtag(self, tag, attrs):
        t = tag.lower()
        
        if self.preserve_stack:
            self.emit(self.get_starttag_text() or f'<{tag} />')
            return
        
        if self._is_drop_void(tag, attrs):
            return
        
        if t in ANIMATION_ELEMENTS and is_dangerous_animation_element(tag, attrs):
            return
        
        if t in RAW_TEXT_ELEMENTS:
            if t in PRESERVE_RAW:
                self.preserve_stack.append(t)
                self.emit(self.get_starttag_text() or f'<{tag}>')
            else:
                self.drop_stack.append(t)
            return
        
        safe_attrs, has_dangerous = self._process_attrs(tag, attrs)
        has_dups = has_duplicate_attrs(attrs)
        
        if not has_dangerous and not has_dups:
            raw = self.get_starttag_text()
            if raw:
                self.emit(raw)
                return
        
        self._emit_starttag(tag, safe_attrs, True)
    
    def handle_endtag(self, tag):
        t = tag.lower()
        
        if self.preserve_stack and t == self.preserve_stack[-1]:
            self.emit(f'</{tag}>')
            self.preserve_stack.pop()
            return
        
        if self.drop_stack:
            if t == self.drop_stack[-1]:
                self.drop_stack.pop()
            return
        
        self.emit(f'</{tag}>')
    
    def handle_data(self, data):
        if self.preserve_stack:
            self.emit(data)
        elif not self.drop_stack:
            self.emit(data)
    
    def handle_entityref(self, name):
        if self.preserve_stack or not self.drop_stack:
            self.emit(f'&{name};')
    
    def handle_charref(self, name):
        if self.preserve_stack or not self.drop_stack:
            self.emit(f'&#{name};')
    
    def handle_comment(self, data):
        if self.preserve_stack:
            self.emit(f'<!--{data}-->')
        elif not self.drop_stack:
            d = data.lower().strip()
            if not d.startswith('[if ') and 'script' not in d:
                self.emit(f'<!--{data}-->')
    
    def handle_decl(self, decl):
        if not self.preserve_stack and not self.drop_stack:
            self.emit(f'<!{decl}>')
    
    def unknown_decl(self, data):
        if not self.preserve_stack and not self.drop_stack:
            self.emit(f'<![{data}]>')
    
    def get_output(self):
        return ''.join(self.output)


def filter_html(html):
    parser = HTMLFilter(convert_charrefs=False)
    parser.feed(html)
    parser.close()
    return parser.get_output()


def main():
    if len(sys.argv) < 2:
        print("Usage: filter.py <html_file>", file=sys.stderr)
        sys.exit(1)
    
    with open(sys.argv[1], 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    filtered = filter_html(content)
    
    with open(sys.argv[1], 'w', encoding='utf-8') as f:
        f.write(filtered)


if __name__ == '__main__':
    main()
