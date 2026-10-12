FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir \
    build==1.3.0 \
    packaging==25.0 \
    pytest==8.4.1 \
    setuptools==75.6.0 \
    wheel==0.45.1

WORKDIR /app
COPY tools/devpkg_index.py /usr/local/bin/devpkg-index
COPY data/index-credentials.txt /opt/devpkg-index/credentials.txt
COPY project/vectorops /opt/bootstrap/vectorops
COPY project/vectorops /app/vectorops

RUN chmod +x /usr/local/bin/devpkg-index \
    && python3 -m build /opt/bootstrap/vectorops \
    && mkdir -p /opt/devpkg-index/bootstrap/packages \
    && cp /opt/bootstrap/vectorops/dist/* /opt/devpkg-index/bootstrap/packages/
