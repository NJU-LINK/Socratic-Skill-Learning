#!/bin/bash
set -e
exec python3 <<'PYEOF'
import json

from pptx import Presentation
from pptx.util import Inches, Pt


prs = Presentation("/app/input.pptx")
layout = next(
    candidate
    for candidate in prs.slide_layouts
    if candidate.name == "Slide 1 master"
)
slide = prs.slides.add_slide(layout)
box = slide.shapes.add_textbox(
    Inches(1),
    Inches(1),
    Inches(8),
    Inches(2),
)
paragraph = box.text_frame.paragraphs[0]
run = paragraph.add_run()
run.text = "Summary"
run.font.size = Pt(36)
run.font.bold = True

report = {
    "changes": [
        {
            "action": "add_slide",
            "current_slide": 11,
            "layout": "Slide 1 master",
        },
        {
            "action": "add_textbox",
            "current_slide": 11,
            "text": "Summary",
            "left_inches": 1,
            "top_inches": 1,
            "width_inches": 8,
            "height_inches": 2,
            "font_size_pt": 36,
            "bold": True,
        },
    ]
}

prs.save("/app/output.pptx")
with open("/app/report.json", "w", encoding="utf-8") as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)
PYEOF
