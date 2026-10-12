FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620

RUN sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true \
    && sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir \
        beautifulsoup4==4.13.4 \
        pytest==8.4.1 \
        selenium==4.35.0

# Private benchmark files are removed from the build context before Docker sees
# it. Copy only the public input directories used by a particular variant;
# source generators and build metadata must not become agent-visible fixtures.
COPY . /tmp/task-context/
RUN mkdir -p /app \
    && for entry in fixtures data samples; do \
         if [ -e "/tmp/task-context/${entry}" ]; then \
           cp -a "/tmp/task-context/${entry}" "/app/${entry}"; \
         fi; \
       done \
    && rm -rf /tmp/task-context

WORKDIR /app
