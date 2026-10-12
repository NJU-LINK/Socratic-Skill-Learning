FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620

RUN python3 -m pip install --no-cache-dir \
    beautifulsoup4==4.13.4 \
    pytest==8.4.1

WORKDIR /app
COPY fixtures/tainted/ /app/fixtures/
