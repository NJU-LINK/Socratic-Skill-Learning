"""
Reference implementation for office-workflow: email filtering to TXT.

Demonstrates the core pattern: parse source artifacts → filter → format → write.

Reads .eml files from a specified directory, filters by exact Subject match,
extracts plain-text bodies, and writes a formatted TXT output sorted by filename.
"""
import os
import glob
from email import policy
from email.parser import BytesParser


def run():
    """
    Main workflow function.
    Reads data/emails/Bob/*.eml, selects messages with Subject
    'scheduled meeting' or 'application approved', writes data/answer.txt.
    """
    # Configuration from task instruction
    email_dir = "data/emails/Bob/"
    target_subjects = {"scheduled meeting", "application approved"}
    output_file = "data/answer.txt"

    # Parse all .eml files
    eml_files = glob.glob(os.path.join(email_dir, "*.eml"))

    selected = []
    for filepath in eml_files:
        # Critical: use policy.default for clean header decoding
        with open(filepath, "rb") as f:
            msg = BytesParser(policy=policy.default).parse(f)

        subject = msg["Subject"]

        # Exact, case-sensitive match
        if subject in target_subjects:
            # Extract plain-text body from MIME structure
            body_part = msg.get_body(preferencelist=("plain",))
            body = body_part.get_content().strip() if body_part else ""

            filename = os.path.basename(filepath)
            selected.append((filename, subject, body))

    # Sort by source filename
    selected.sort(key=lambda x: x[0])

    # Build output: blocks separated by blank lines, file ends with one newline
    blocks = []
    for filename, subject, body in selected:
        blocks.append(f"Subject: {subject}\n{body}")

    output = "\n\n".join(blocks) + "\n"

    with open(output_file, "w") as f:
        f.write(output)


if __name__ == "__main__":
    run()
