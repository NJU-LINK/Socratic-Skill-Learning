#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree


INPUT = Path("/app/input.pptx")
OUTPUT = Path("/app/output.pptx")
SLIDE = "ppt/slides/slide1.xml"
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def title_shape(root):
    shapes = root.xpath(".//p:sp", namespaces=NS)
    for shape in shapes:
        placeholders = shape.xpath(
            "./p:nvSpPr/p:nvPr/p:ph[@type='title' or @type='ctrTitle']",
            namespaces=NS,
        )
        if placeholders:
            return shape
    return next(
        shape
        for shape in shapes
        if "".join(shape.xpath(".//a:t/text()", namespaces=NS)).strip()
    )


with ZipFile(INPUT) as source:
    entries = source.infolist()
    parts = {entry.filename: source.read(entry.filename) for entry in entries}

slide = etree.fromstring(parts[SLIDE])
shape = title_shape(slide)
texts = shape.xpath(".//a:t", namespaces=NS)
if not texts:
    raise RuntimeError("title shape contains no text")
old = "".join(text.text or "" for text in texts).strip()
texts[0].text = "Deep Sea Exploration"
for text in texts[1:]:
    text.text = ""

run = texts[0].getparent()
run_properties = run.find("a:rPr", namespaces=NS)
if run_properties is None:
    run_properties = etree.Element(f"{{{NS['a']}}}rPr")
    run.insert(0, run_properties)
run_properties.set("b", "1")
parts[SLIDE] = etree.tostring(
    slide,
    encoding="UTF-8",
    xml_declaration=True,
    standalone=True,
)

with ZipFile(OUTPUT, "w") as target:
    for entry in entries:
        target.writestr(entry, parts[entry.filename])

report = {
    "changes": [
        {
            "action": "change_title",
            "slide": 1,
            "old": old,
            "new": "Deep Sea Exploration",
        },
        {
            "action": "set_font",
            "slide": 1,
            "target": "Deep Sea Exploration",
            "property": "bold",
            "value": True,
        },
    ]
}
Path("/app/report.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
PY
