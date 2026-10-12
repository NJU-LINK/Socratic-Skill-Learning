FROM python:3.11-slim

RUN pip install --no-cache-dir pytest==7.4.4

WORKDIR /app
COPY tsla_prices.json /app/tsla_prices.json
