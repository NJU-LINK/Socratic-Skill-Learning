FROM python:3.11-slim

RUN pip install --no-cache-dir pytest==7.4.4

WORKDIR /app
RUN mkdir -p /app/financials
COPY wuliangye_financials.html /app/financials/wuliangye_financials.html
