#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import json
import posixpath
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from zipfile import ZipFile

from lxml import etree


INPUT = Path("/app/input.pptx")
OUTPUT = Path("/app/output.pptx")
PRESENTATION = "ppt/presentation.xml"
PRESENTATION_RELS = "ppt/_rels/presentation.xml.rels"
CONTENT_TYPES = "[Content_Types].xml"
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
}


def resolve_target(source_part, target):
    if target.startswith("/"):
        return unquote(target.lstrip("/"))
    return unquote(posixpath.normpath(posixpath.join(
        posixpath.dirname(source_part),
        target,
    )))


def relationship_part(source_part):
    path = PurePosixPath(source_part)
    return str(path.parent / "_rels" / f"{path.name}.rels")


def related_targets(parts, relationship_name, source_part):
    root = etree.fromstring(parts[relationship_name])
    return [
        resolve_target(source_part, relationship.get("Target"))
        for relationship in root.xpath("./rel:Relationship", namespaces=NS)
        if relationship.get("TargetMode") != "External"
    ]


def reachable_package_parts(parts):
    reachable = {CONTENT_TYPES, "_rels/.rels"}
    pending = related_targets(parts, "_rels/.rels", "")
    while pending:
        part = pending.pop()
        if part in reachable:
            continue
        if part not in parts:
            raise RuntimeError(f"relationship target is missing: {part}")
        reachable.add(part)
        rels = relationship_part(part)
        if rels in parts:
            reachable.add(rels)
            pending.extend(related_targets(parts, rels, part))
    return reachable


def remove_unreachable_content_type_overrides(parts, reachable):
    root = etree.fromstring(parts[CONTENT_TYPES])
    for override in root.xpath("./ct:Override", namespaces=NS):
        part = unquote(override.get("PartName").lstrip("/"))
        if part not in reachable:
            override.getparent().remove(override)
    parts[CONTENT_TYPES] = etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        standalone=True,
    )


def title_shape(root):
    shapes = root.xpath(".//p:sp", namespaces=NS)
    for shape in shapes:
        if shape.xpath(
            "./p:nvSpPr/p:nvPr/p:ph[@type='title' or @type='ctrTitle']",
            namespaces=NS,
        ):
            return shape
    return next(
        shape
        for shape in shapes
        if "".join(shape.xpath(".//a:t/text()", namespaces=NS)).strip()
    )


with ZipFile(INPUT) as source:
    entries = source.infolist()
    parts = {entry.filename: source.read(entry.filename) for entry in entries}

presentation = etree.fromstring(parts[PRESENTATION])
relationships = etree.fromstring(parts[PRESENTATION_RELS])
slide_ids = presentation.xpath("./p:sldIdLst/p:sldId", namespaces=NS)
if len(slide_ids) != 11:
    raise RuntimeError(f"expected 11 source slides, found {len(slide_ids)}")

relationship_by_id = {
    relationship.get("Id"): relationship
    for relationship in relationships.xpath("./rel:Relationship", namespaces=NS)
}
target_rid = slide_ids[6].get(f"{{{NS['r']}}}id")
target_part = resolve_target(
    PRESENTATION,
    relationship_by_id[target_rid].get("Target"),
)

for original_index in (5, 3):
    deleted = slide_ids[original_index]
    deleted_rid = deleted.get(f"{{{NS['r']}}}id")
    deleted.getparent().remove(deleted)
    relationships.remove(relationship_by_id[deleted_rid])

target_slide = etree.fromstring(parts[target_part])
shape = title_shape(target_slide)
texts = shape.xpath(".//a:t", namespaces=NS)
if not texts:
    raise RuntimeError("target title contains no text")
old = "".join(text.text or "" for text in texts).strip()
texts[0].text = "深海物种概述"
for text in texts[1:]:
    text.text = ""
run = texts[0].getparent()
run_properties = run.find("a:rPr", namespaces=NS)
if run_properties is None:
    run_properties = etree.Element(f"{{{NS['a']}}}rPr")
    run.insert(0, run_properties)
run_properties.set("b", "1")

parts[PRESENTATION] = etree.tostring(
    presentation,
    encoding="UTF-8",
    xml_declaration=True,
    standalone=True,
)
parts[PRESENTATION_RELS] = etree.tostring(
    relationships,
    encoding="UTF-8",
    xml_declaration=True,
    standalone=True,
)
parts[target_part] = etree.tostring(
    target_slide,
    encoding="UTF-8",
    xml_declaration=True,
    standalone=True,
)

reachable = reachable_package_parts(parts)
remove_unreachable_content_type_overrides(parts, reachable)
with ZipFile(OUTPUT, "w") as target:
    for entry in entries:
        name = entry.filename
        if name.endswith("/"):
            if any(part.startswith(name) for part in reachable):
                target.writestr(entry, parts[name])
        elif name in reachable:
            target.writestr(entry, parts[name])

report = {
    "changes": [
        {"action": "delete_slide", "original_slide": 6},
        {"action": "delete_slide", "original_slide": 4},
        {
            "action": "change_title",
            "original_slide": 7,
            "current_slide": 5,
            "old": old,
            "new": "深海物种概述",
            "bold": True,
        },
    ]
}
Path("/app/report.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
PY
