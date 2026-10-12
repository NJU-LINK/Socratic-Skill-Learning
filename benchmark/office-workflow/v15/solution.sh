#!/usr/bin/env bash
set -euo pipefail

cat > /app/solve.py <<'PY'
from email import policy
from email.parser import BytesParser
from pathlib import Path
from textwrap import wrap

from reportlab.pdfgen import canvas


def run() -> None:
    for source in sorted(Path("data/emails").rglob("*.eml")):
        message = BytesParser(policy=policy.default).parsebytes(source.read_bytes())
        recipient = str(message["To"]).split("@", 1)[0]
        destination = Path("data") / recipient / f"{source.stem}.pdf"
        destination.parent.mkdir(parents=True, exist_ok=True)

        body_part = message.get_body(preferencelist=("plain",))
        body = body_part.get_content() if body_part is not None else ""
        pdf = canvas.Canvas(str(destination))
        pdf.drawString(72, 770, f"Subject: {message['Subject']}")
        y = 745
        for line in body.splitlines():
            if line.strip():
                for visual_line in wrap(line, width=85):
                    pdf.drawString(72, y, visual_line)
                    y -= 16
        pdf.save()


if __name__ == "__main__":
    run()
PY

python3 /app/solve.py
