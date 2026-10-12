#!/usr/bin/env python3
import json
from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


SOURCE_DIR = Path("/tmp/original_documents")
SPEC_PATH = Path("/root/document_specs.json")


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def create_pdf(path: Path, title: str, lines: list[str]) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - 72

    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, y, title)
    y -= 30

    c.setFont("Helvetica", 11)
    for line in lines:
        wrapped = wrap(line, width=88) or [""]
        for part in wrapped:
            if y < 72:
                c.showPage()
                y = height - 72
                c.setFont("Helvetica", 11)
            c.drawString(72, y, part)
            y -= 16

    c.save()


def create_jpg(path: Path, title: str, lines: list[str]) -> None:
    image = Image.new("RGB", (1700, 2200), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(54)
    body_font = load_font(36)

    y = 120
    draw.text((120, y), title, fill="black", font=title_font)
    y += 120

    for line in lines:
        wrapped = wrap(line, width=55) or [""]
        for part in wrapped:
            draw.text((120, y), part, fill="black", font=body_font)
            y += 58

    image.save(path, format="JPEG", quality=95)


def main() -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    specs = json.loads(SPEC_PATH.read_text())

    for spec in specs:
        path = SOURCE_DIR / spec["filename"]
        if spec["format"] == "pdf":
            create_pdf(path, spec["title"], spec["lines"])
        elif spec["format"] == "jpg":
            create_jpg(path, spec["title"], spec["lines"])
        else:
            raise ValueError(f"Unsupported format: {spec['format']}")


if __name__ == "__main__":
    main()
