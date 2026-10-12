FROM python:3.11-slim

RUN pip install --no-cache-dir \
    lxml==5.4.0 \
    python-pptx==1.0.2 \
    pytest==8.4.1

WORKDIR /app
COPY input.pptx /app/input.pptx
