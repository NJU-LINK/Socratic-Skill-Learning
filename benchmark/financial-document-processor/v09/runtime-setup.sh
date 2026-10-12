#!/bin/bash
set -euo pipefail

sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    imagemagick \
    poppler-utils \
    python3 \
    python3-pil \
    python3-venv \
    tesseract-ocr

uv venv /opt/financial-doc-venv
uv pip install --python /opt/financial-doc-venv/bin/python \
    pillow==11.3.0 \
    pymupdf==1.25.2 \
    pypdf==6.1.1 \
    pypdfium2==4.30.0 \
    pytesseract==0.3.13 \
    pytest==7.4.4
