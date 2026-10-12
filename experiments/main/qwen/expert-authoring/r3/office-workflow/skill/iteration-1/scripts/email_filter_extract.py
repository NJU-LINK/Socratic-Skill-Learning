"""
Reusable email filter-and-extract module.

Usage:
    from email_filter_extract import parse_eml, get_text_body, filter_and_write

    # Or use as a template inside solve.py.
"""

import email
import email.policy
import glob
import os


def parse_eml(path):
    """Parse a .eml file and return a Message object with default policy."""
    with open(path, "rb") as f:
        return email.message_from_binary_file(f, policy=email.policy.default)


def get_text_body(msg):
    """Return the decoded, stripped plain-text body from a MIME message.

    Walks multipart structures and returns the first text/plain part found.
    For non-multipart messages, decodes and strips the content directly.
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


def filter_and_write(email_dir, target_subjects, output_path, sort_key=None):
    """Read .eml files, filter by exact subject match, write formatted output.

    Args:
        email_dir:      Directory containing .eml files.
        target_subjects: Set of exact Subject strings to select.
        output_path:    Path for the output .txt file.
        sort_key:       Callable for sorting; defaults to filename (basename).
    """
    if sort_key is None:
        sort_key = lambda p: os.path.basename(p)

    eml_files = sorted(glob.glob(os.path.join(email_dir, "*.eml")), key=sort_key)

    blocks = []
    for filepath in eml_files:
        msg = parse_eml(filepath)
        subject = msg.get("Subject", "")
        if subject not in target_subjects:
            continue
        body = get_text_body(msg)
        blocks.append(f"Subject: {subject}\n{body}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n\n".join(blocks) + "\n")

    return blocks


if __name__ == "__main__":
    import sys
    email_dir = sys.argv[1] if len(sys.argv) > 1 else "data/emails/Bob"
    subjects = set(sys.argv[2:]) if len(sys.argv) > 2 else {"scheduled meeting", "application approved"}
    output = "data/answer.txt"
    result = filter_and_write(email_dir, subjects, output)
    print(f"Wrote {len(result)} block(s) to {output}")
