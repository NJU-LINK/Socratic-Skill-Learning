FROM python:3.11-slim

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources || true \
    && apt-get -o Acquire::Retries=3 update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends file sqlite3 xxd \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest==8.4.1

COPY fragments/ /app/fragments/
WORKDIR /app
