#!/bin/bash
set -euo pipefail

cat <<'PY' > /app/filter.py
from __future__ import annotations

import html
import re
import sys
from pathlib import Path
from urllib.parse import unquote


ATTR_RE = re.compile(r'(?P<prefix>\s)(?P<name>action|formaction|href)\s*=\s*(?P<quote>["\'])(?P<value>.*?)(?P=quote)', re.IGNORECASE | re.DOTALL)
META_REFRESH_RE = re.compile(r'<meta\b(?P<attrs>[^>]*\bhttp-equiv\s*=\s*(["\'])?refresh\2?[^>]*)>', re.IGNORECASE | re.DOTALL)
CONTENT_RE = re.compile(r'(?P<prefix>\scontent\s*=\s*)(?P<quote>["\'])(?P<value>.*?)(?P=quote)', re.IGNORECASE | re.DOTALL)
URL_IN_REFRESH_RE = re.compile(r'(?P<head>^\s*\d+(?:\.\d+)?\s*;\s*url\s*=\s*)(?P<url>.*)\s*$', re.IGNORECASE | re.DOTALL)


def decode_for_scheme_check(value: str) -> str:
    candidate = html.unescape(value.strip())
    previous = None
    for _ in range(3):
        if candidate == previous:
            break
        previous = candidate
        candidate = html.unescape(unquote(candidate))
    return re.sub(r'[\x00-\x20]+', '', candidate).lower()


def is_dangerous_url(value: str) -> bool:
    normalized = decode_for_scheme_check(value)
    return normalized.startswith('javascript:') or normalized.startswith('data:text/html')


def sanitize_url_attributes(html: str) -> str:
    def repl(match: re.Match[str]) -> str:
        value = match.group('value')
        if not is_dangerous_url(value):
            return match.group(0)
        return f"{match.group('prefix')}{match.group('name')}={match.group('quote')}#{match.group('quote')}"

    return ATTR_RE.sub(repl, html)


def sanitize_meta_refresh(html: str) -> str:
    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        content_match = CONTENT_RE.search(tag)
        if not content_match:
            return tag
        content_value = content_match.group('value')
        refresh_match = URL_IN_REFRESH_RE.match(content_value)
        if not refresh_match:
            return tag
        url = refresh_match.group('url')
        if not is_dangerous_url(url):
            return tag
        replacement = f"{refresh_match.group('head')}#"
        return tag[:content_match.start('value')] + replacement + tag[content_match.end('value'):]

    return META_REFRESH_RE.sub(repl, html)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit('usage: python /app/filter.py <html-file>')

    path = Path(sys.argv[1])
    html = path.read_text(encoding='utf-8')
    sanitized = sanitize_meta_refresh(sanitize_url_attributes(html))
    path.write_text(sanitized, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
PY

chmod +x /app/filter.py
