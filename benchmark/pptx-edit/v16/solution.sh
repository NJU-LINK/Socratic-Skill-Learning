#!/bin/bash
set -e
exec python3 <<'PYEOF'
import json

from pptx import Presentation


prs = Presentation("/app/input.pptx")
title = next(
    shape
    for shape in prs.slides[0].shapes
    if shape.has_text_frame and shape.text.strip() == "探索深海：哈达尔区"
)
title.text_frame.paragraphs[0].runs[0].text = "深海探索"
for paragraph in title.text_frame.paragraphs:
    for run in paragraph.runs:
        run.font.bold = True

slide_id = prs.slides._sldIdLst[3]
relationship_id = slide_id.get(
    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
)
prs.part.drop_rel(relationship_id)
prs.slides._sldIdLst.remove(slide_id)

notes = "Updated title and removed redundant slide."
prs.slides[0].notes_slide.notes_text_frame.text = notes

report = {
    "changes": [
        {
            "action": "change_title",
            "original_slide": 1,
            "current_slide": 1,
            "old": "探索深海：哈达尔区",
            "new": "深海探索",
            "bold": True,
        },
        {"action": "delete_slide", "original_slide": 4},
        {
            "action": "add_notes",
            "original_slide": 1,
            "current_slide": 1,
            "text": notes,
        },
    ]
}

prs.save("/app/output.pptx")
with open("/app/report.json", "w", encoding="utf-8") as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)
PYEOF
