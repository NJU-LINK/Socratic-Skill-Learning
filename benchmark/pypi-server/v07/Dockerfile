FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir \
    build==1.3.0 \
    pytest==8.4.1 \
    setuptools==75.6.0 \
    wheel==0.45.1

WORKDIR /app
COPY package-src /app/package-src
COPY simple /app/simple
RUN mkdir -p /app/dist
