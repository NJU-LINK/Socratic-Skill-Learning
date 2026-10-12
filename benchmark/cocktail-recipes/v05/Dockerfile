FROM python:3.11-slim

RUN pip install --no-cache-dir pytest==8.4.1 jsonschema==4.25.1

WORKDIR /app
COPY format_spec.json .
COPY task.json .
COPY knowledge/source_a.txt ./knowledge/source_a.txt
COPY knowledge/source_b.txt ./knowledge/source_b.txt
COPY knowledge/source_c.txt ./knowledge/source_c.txt
