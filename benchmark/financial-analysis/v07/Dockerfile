FROM python:3.11-slim

RUN pip install --no-cache-dir pytest==7.4.4

WORKDIR /app
RUN mkdir -p /app/financials
COPY income_statement.csv /app/financials/income_statement.csv
COPY balance_sheet.csv /app/financials/balance_sheet.csv
