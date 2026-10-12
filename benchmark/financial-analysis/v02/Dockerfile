FROM python:3.11-slim

RUN pip install --no-cache-dir pytest==7.4.4

WORKDIR /app
RUN mkdir -p /app/financials
COPY amd_financials.html /app/financials/amd_financials.html
COPY decoy_quarterly.html /app/financials/decoy_quarterly.html
COPY decoy_nvidia.html /app/financials/decoy_nvidia.html
