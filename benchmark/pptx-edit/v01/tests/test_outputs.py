import json, os
from pptx import Presentation
from pptx.util import Pt, Emu
from pptx.dml.color import RGBColor

def load():
    return Presentation("/app/output.pptx")

def load_report():
    try:
        with open("/app/report.json") as f:
            return json.load(f)
    except:
        return {}

def test_output_exists():
    assert os.path.exists("/app/output.pptx"), "output.pptx not found"

def test_no_empty_output():
    prs = load()
    assert len(prs.slides) > 0, "No slides in output"


def test_change_title():
    prs = load()
    found = False
    for shape in prs.slides[0].shapes:
        if shape.has_text_frame and "Deep Sea Exploration" in shape.text:
            found = True
            break
    assert found, "Title 'Deep Sea Exploration' not found on slide 0"


def test_font_prop():
    prs = load()
    found_bold = False
    for shape in prs.slides[0].shapes:
        if shape.has_text_frame:
            for p in shape.text_frame.paragraphs:
                for r in p.runs:
                    if "Deep Sea Exploration" in r.text:
                        found_bold = found_bold or r.font.bold
    assert found_bold, "Bold text 'Deep Sea Exploration' not found on slide 1"
