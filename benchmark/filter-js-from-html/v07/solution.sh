#!/bin/bash
set -euo pipefail

cat <<'PY' > /app/filter.py
from __future__ import annotations

import html
import sys
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup


URL_ATTRS = ("href", "action", "formaction", "src", "data")
SAFE_REPLACEMENT = "#"
EMPTY_URL_ATTRS = {
    ("iframe", "src"),
    ("frame", "src"),
    ("embed", "src"),
    ("object", "data"),
}


def normalize_url(value: str) -> str:
    normalized = value
    for _ in range(3):
        updated = html.unescape(unquote(normalized))
        if updated == normalized:
            break
        normalized = updated
    compact = "".join(normalized.split())
    return compact.lower()


def is_dangerous_url(value: str) -> bool:
    normalized = normalize_url(value)
    return normalized.startswith("javascript:") or normalized.startswith("data:text/html")


def sanitize_url_attrs(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(True):
        for attr in URL_ATTRS:
            if attr in tag.attrs:
                raw_value = tag.get(attr)
                if isinstance(raw_value, str) and is_dangerous_url(raw_value):
                    if (tag.name, attr) in EMPTY_URL_ATTRS:
                        tag[attr] = ""
                    else:
                        tag[attr] = SAFE_REPLACEMENT


def sanitize_refresh_meta(soup: BeautifulSoup) -> None:
    for tag in soup.find_all("meta"):
        http_equiv = tag.get("http-equiv")
        content = tag.get("content")
        if not isinstance(http_equiv, str) or not isinstance(content, str):
            continue
        if http_equiv.strip().lower() != "refresh":
            continue

        lowered = normalize_url(content)
        if "url=javascript:" in lowered or "url=data:text/html" in lowered:
            tag.decompose()


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python /app/filter.py <html-file>")

    html_path = Path(sys.argv[1])
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    sanitize_url_attrs(soup)
    sanitize_refresh_meta(soup)
    html_path.write_text(str(soup), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
