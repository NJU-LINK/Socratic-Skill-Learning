#!/usr/bin/env bash
set -euo pipefail

cat > /app/solve.py <<'PY'
from email import policy
from email.parser import BytesParser
from pathlib import Path


TARGET_SUBJECTS = {"scheduled meeting", "application approved"}


def run() -> None:
    selected: list[tuple[str, str]] = []
    for path in sorted(Path("data/emails/Bob").glob("*.eml")):
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        subject = str(message["Subject"])
        if subject not in TARGET_SUBJECTS:
            continue
        body_part = message.get_body(preferencelist=("plain",))
        body = body_part.get_content().strip() if body_part is not None else ""
        selected.append((subject, body))

    output = "\n\n".join(
        f"Subject: {subject}\n{body}"
        for subject, body in selected
    )
    Path("data/answer.txt").write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
PY

python3 /app/solve.py
