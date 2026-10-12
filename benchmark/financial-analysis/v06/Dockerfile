FROM python:3.11-slim

RUN pip install --no-cache-dir pytest==7.4.4 openpyxl==3.1.5

WORKDIR /app
RUN mkdir -p /app/financials
COPY msft_data.csv /app/financials/msft_data.csv
