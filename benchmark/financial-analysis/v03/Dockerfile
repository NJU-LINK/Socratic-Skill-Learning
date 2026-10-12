FROM python:3.11-slim

RUN pip install --no-cache-dir pytest==7.4.4

WORKDIR /app
RUN mkdir -p /app/financials
COPY intel_data.json /app/financials/intel_data.json
