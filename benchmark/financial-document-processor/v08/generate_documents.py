#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["Pillow==11.3.0", "reportlab==4.4.3"]
# ///

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

PAGE_SIZE = (1240, 1754)
PAGE_BACKGROUND = (242, 239, 234)
TEXT_COLOR = (42, 42, 42)
RNG = random.Random(20250801)


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def add_stamp(image: Image.Image, text: str) -> Image.Image:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    stamp_font = load_font(120, bold=True)
    bbox = draw.textbbox((0, 0), text, font=stamp_font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    position = ((image.width - width) // 2, (image.height - height) // 2)
    draw.rounded_rectangle(
        [position[0] - 26, position[1] - 20, position[0] + width + 26, position[1] + height + 20],
        radius=16,
        outline=(150, 40, 40, 120),
        width=6,
    )
    draw.text(position, text, font=stamp_font, fill=(160, 45, 45, 96))
    layer = layer.rotate(RNG.uniform(-18, 18), resample=Image.Resampling.BICUBIC, expand=False)
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def add_noise(image: Image.Image) -> Image.Image:
    noise = Image.effect_noise(image.size, 10).convert("L")
    noise = ImageEnhance.Contrast(noise).enhance(0.65)
    noise_rgb = ImageOps.colorize(noise, black="#d8d4cf", white="#faf9f6")
    blended = Image.blend(image, noise_rgb, 0.08)
    shadow = Image.new("RGB", image.size, PAGE_BACKGROUND)
    shadow_draw = ImageDraw.Draw(shadow)
    for _ in range(4):
        x = RNG.randint(70, image.width - 180)
        y = RNG.randint(120, image.height - 120)
        shadow_draw.rectangle([x, y, x + RNG.randint(70, 160), y + RNG.randint(10, 22)], fill=(230, 228, 224))
    return ImageChops.multiply(blended, shadow)


def render_jpg_document(doc: dict, output_dir: Path) -> None:
    image = Image.new("RGB", PAGE_SIZE, PAGE_BACKGROUND)
    draw = ImageDraw.Draw(image)

    title_font = load_font(54, bold=True)
    body_font = load_font(32)
    small_font = load_font(26)
    y = 110

    draw.text((100 + RNG.randint(-6, 6), y), doc["heading"], font=title_font, fill=TEXT_COLOR)
    y += 95
    draw.line((100, y, image.width - 100, y), fill=(165, 165, 165), width=3)
    y += 42

    if doc.get("subheading"):
        draw.text((102, y), doc["subheading"], font=small_font, fill=(88, 88, 88))
        y += 56

    for line in doc["lines"]:
        draw.text((100 + RNG.randint(-4, 4), y), line, font=body_font, fill=TEXT_COLOR)
        y += 52

    footer = doc.get("footer")
    if footer:
        y += 18
        draw.line((100, y, image.width - 100, y), fill=(190, 190, 190), width=2)
        y += 28
        draw.text((100, y), footer, font=small_font, fill=(100, 100, 100))

    if doc.get("stamp"):
        image = add_stamp(image, doc["stamp"])

    image = image.rotate(doc.get("rotation", RNG.uniform(-3.2, 3.2)), resample=Image.Resampling.BICUBIC, expand=True, fillcolor=PAGE_BACKGROUND)
    image = ImageOps.fit(image, PAGE_SIZE, method=Image.Resampling.BICUBIC, centering=(0.5, 0.5))
    image = add_noise(image)
    image = ImageEnhance.Contrast(image).enhance(0.9)
    image = ImageEnhance.Brightness(image).enhance(0.98)
    image = image.filter(ImageFilter.GaussianBlur(radius=doc.get("blur", 0.75)))
    image.save(output_dir / doc["filename"], format="JPEG", quality=44, optimize=True)


def render_pdf_document(doc: dict, output_dir: Path) -> None:
    path = output_dir / doc["filename"]
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4

    pdf.setFillColorRGB(0.98, 0.98, 0.97)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)

    pdf.setStrokeColorRGB(0.75, 0.75, 0.75)
    pdf.line(48, height - 90, width - 48, height - 90)
    pdf.setFillColor(Color(0.12, 0.12, 0.12, alpha=1))
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(50, height - 62, doc["heading"])

    y = height - 118
    if doc.get("subheading"):
        pdf.setFont("Helvetica", 10)
        pdf.setFillColorRGB(0.38, 0.38, 0.38)
        pdf.drawString(52, y, doc["subheading"])
        y -= 24

    pdf.setFont("Helvetica", 12)
    pdf.setFillColorRGB(0.15, 0.15, 0.15)
    for line in doc["lines"]:
        pdf.drawString(52, y, line)
        y -= 20

    if doc.get("footer"):
        y -= 10
        pdf.setStrokeColorRGB(0.82, 0.82, 0.82)
        pdf.line(50, y, width - 50, y)
        y -= 18
        pdf.setFont("Helvetica", 10)
        pdf.setFillColorRGB(0.42, 0.42, 0.42)
        pdf.drawString(52, y, doc["footer"])

    pdf.save()


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: generate_documents.py SPEC_PATH OUTPUT_DIR")

    spec_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    specs = json.loads(spec_path.read_text())
    for doc in specs["documents"]:
        if doc["file_type"] == "jpg":
            render_jpg_document(doc, output_dir)
        elif doc["file_type"] == "pdf":
            render_pdf_document(doc, output_dir)
        else:
            raise ValueError(f"unsupported file type: {doc['file_type']}")


if __name__ == "__main__":
    main()
