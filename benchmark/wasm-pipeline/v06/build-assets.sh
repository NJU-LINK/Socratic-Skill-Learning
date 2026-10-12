#!/bin/bash
set -euo pipefail

install -m 0644 /tmp/task/header_layout.txt /app/header_layout.txt
python3 /tmp/task/make_sample_assets.py /app
