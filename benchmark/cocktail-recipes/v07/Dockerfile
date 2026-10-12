FROM python:3.11-slim

RUN pip install --no-cache-dir pytest==8.4.1 jsonschema==4.25.1

WORKDIR /app
COPY format_spec.json .
COPY task.json .
COPY knowledge/ ./knowledge/
