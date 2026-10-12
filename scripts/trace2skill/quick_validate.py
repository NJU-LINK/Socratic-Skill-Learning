#!/usr/bin/env python3
"""Compatibility validator for the path referenced by Trace2Skill at its pinned commit."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: quick_validate.py <skill-directory>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    skill = root / "SKILL.md"
    if not skill.is_file():
        print("SKILL.md is missing", file=sys.stderr)
        return 1
    text = skill.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]+)$", text)
    if not match:
        print("SKILL.md requires YAML frontmatter and a non-empty body", file=sys.stderr)
        return 1
    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict):
        print("frontmatter must be a YAML mapping", file=sys.stderr)
        return 1
    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        print("frontmatter name must be lowercase-hyphenated", file=sys.stderr)
        return 1
    if not isinstance(description, str) or not description.strip():
        print("frontmatter description must be non-empty", file=sys.stderr)
        return 1
    if not match.group(2).strip():
        print("SKILL.md body must be non-empty", file=sys.stderr)
        return 1
    print("Skill is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
