"""
v01 solution: Parse MIME emails, filter by Subject, write formatted TXT.

Task: Read every .eml file in data/emails/Bob/ with a MIME-aware email parser.
Select only messages whose Subject is exactly "scheduled meeting" or
"application approved". Sort by source filename. Write data/answer.txt with
one block per selected message:

    Subject: <the complete Subject header>
    <the complete, stripped plain-text body>

Separate adjacent blocks with one blank line and end the file with one newline.
"""

import email
import os
import glob
from email import policy


def run():
    emails_dir = "data/emails/Bob/"
    output_file = "data/answer.txt"
    target_subjects = {"scheduled meeting", "application approved"}

    # Step 1: Discover source artifacts
    eml_files = sorted(glob.glob(os.path.join(emails_dir, "*.eml")))

    # Step 2 & 3: Parse and apply selection predicate, extract content
    selected = []
    for fpath in eml_files:
        with open(fpath, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)

        subject = msg["subject"]
        if subject in target_subjects:
            # Extract plain-text body from multipart
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_content()
                        break
            else:
                body = msg.get_content()

            # Strip whitespace from body
            body = body.strip()
            selected.append((os.path.basename(fpath), subject, body))

    # Step 4: Sort by filename and format output
    selected.sort(key=lambda x: x[0])

    blocks = []
    for fname, subject, body in selected:
        block = f"Subject: {subject}\n{body}"
        blocks.append(block)

    # Step 5: Write output with correct formatting
    with open(output_file, "w") as f:
        f.write("\n\n".join(blocks) + "\n")


if __name__ == "__main__":
    run()
