FROM python:3.11-slim

RUN pip install --no-cache-dir pytest==7.4.4

WORKDIR /app
COPY msft_prices.csv /app/msft_prices.csv
COPY decoy_log.csv /app/decoy_log.csv
COPY decoy_readme.txt /app/decoy_readme.txt
