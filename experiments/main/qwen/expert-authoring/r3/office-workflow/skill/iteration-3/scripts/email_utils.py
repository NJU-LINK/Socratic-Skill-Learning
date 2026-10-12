"""
Parameterized email utilities for office-workflow tasks.

This module provides reusable helpers. Import and call from solve.py.
All task-specific values (paths, subjects, sort keys) must be passed as
arguments — nothing is hardcoded.

Usage in solve.py:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    from email_utils import parse_eml, get_text_body, filter_emails
"""

import email
import email.policy
import glob
import os


def parse_eml(path):
    """Parse a .eml file with the modern email policy."""
    with open(path, "rb") as f:
        return email.message_from_binary_file(f, policy=email.policy.default)


def get_text_body(msg):
    """Return decoded, stripped plain-text body from a MIME message.

    Walks multipart structures and returns the first text/plain part.
    For non-multipart messages, decodes and strips directly.
    """
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                content = part.get_content()
                if isinstance(content, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    content = content.decode(charset)
                return content.strip()
    else:
        content = msg.get_content()
        if isinstance(content, bytes):
            charset = msg.get_content_charset() or "utf-8"
            content = content.decode(charset)
        return content.strip()
    return ""


def filter_emails(email_dir, subject_set, sort_key=None):
    """Read .eml files, filter by exact subject match, return sorted list.

    Args:
        email_dir:    Directory containing .eml files.
        subject_set:  Set of exact Subject header strings to select.
        sort_key:     Callable(path) → sort value. Defaults to basename.

    Returns:
        List of (filepath, subject, body) tuples, sorted by sort_key.
    """
    if sort_key is None:
        sort_key = lambda p: os.path.basename(p)

    eml_files = sorted(glob.glob(os.path.join(email_dir, "*.eml")), key=sort_key)

    selected = []
    for fpath in eml_files:
        msg = parse_eml(fpath)
        subject = msg.get("Subject", "")
        if subject in subject_set:
            body = get_text_body(msg)
            selected.append((fpath, subject, body))

    return selected


def format_blocks_txt(selected, include_subject=True):
    """Format (filepath, subject, body) tuples into block-separated text.

    Args:
        selected:        List of (filepath, subject, body) tuples.
        include_subject: If True, prepend 'Subject: <subject>' to each block.

    Returns:
        String with blocks separated by one blank line, ending with one newline.
    """
    blocks = []
    for (_fpath, subject, body) in selected:
        if include_subject:
            blocks.append(f"Subject: {subject}\n{body}")
        else:
            blocks.append(body)
    return "\n\n".join(blocks) + "\n"
