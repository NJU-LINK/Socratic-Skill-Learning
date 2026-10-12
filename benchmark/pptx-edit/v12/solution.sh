#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import json
from pathlib import Path

from pptx import Presentation


OLD = "quantum material"
NEW = "Q-Material"
NOTES = "Updated terminology: quantum materials now referred to as Q-Material."

presentation = Presentation("/app/input.pptx")
slide = presentation.slides[0]
changed = False
for shape in slide.shapes:
    if not shape.has_text_frame or OLD not in shape.text:
        continue
    for paragraph in shape.text_frame.paragraphs:
        for run in paragraph.runs:
            if OLD in run.text:
                run.text = run.text.replace(OLD, NEW)
                changed = True
    break
if not changed:
    raise RuntimeError("target phrase was not found in the slide 1 title")

slide.notes_slide.notes_text_frame.text = NOTES
presentation.save("/app/output.pptx")

report = {
    "changes": [
        {
            "action": "replace_text",
            "slide": 1,
            "old": OLD,
            "new": NEW,
        },
        {
            "action": "add_notes",
            "slide": 1,
            "text": NOTES,
        },
    ]
}
Path("/app/report.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
PY
