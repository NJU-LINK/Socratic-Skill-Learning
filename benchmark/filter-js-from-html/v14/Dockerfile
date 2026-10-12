FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620

RUN python3 -m pip install --no-cache-dir \
    beautifulsoup4==4.13.4 \
    pytest==8.4.1

WORKDIR /app
RUN mkdir -p /app/data
COPY data/editorial-fragile-input.html /app/data/
COPY data/editorial-briefing-input.html /app/data/
COPY data/editorial-clean-reference.html /app/data/
COPY data/editorial-notes.txt /app/data/
