FROM python:3.13-slim-bookworm

RUN python -m pip install --no-cache-dir pytest==8.4.1

WORKDIR /app
RUN mkdir -p /app/data
COPY data/bank_transactions.csv /app/data/bank_transactions.csv
