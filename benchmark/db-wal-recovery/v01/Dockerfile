FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

RUN sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true \
    && sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pytest \
        sqlite3 \
        xxd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY main.db /app/main.db
COPY main.db-wal.encrypted /app/main.db-wal
