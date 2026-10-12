FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources || true \
    && apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir pytest==8.4.1

RUN mkdir -p /app && chmod 755 /app
COPY challenge-setup.sh /app/challenge-setup.sh
RUN chmod +x /app/challenge-setup.sh \
    && bash /app/challenge-setup.sh \
    && rm /app/challenge-setup.sh

WORKDIR /app
