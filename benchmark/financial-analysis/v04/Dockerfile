FROM python:3.11-slim

RUN pip install --no-cache-dir pytest==7.4.4

WORKDIR /app
RUN mkdir -p /app/balance
COPY income.csv /app/income.csv
COPY equity.csv /app/balance/equity.csv
