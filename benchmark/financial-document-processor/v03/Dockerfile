FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS build
COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /uvx /bin/

COPY generate_documents.py randomize_filenames.py /build/
WORKDIR /build
RUN uv run /build/generate_documents.py --output /tmp/source_documents \
    && uv run /build/randomize_filenames.py /tmp/source_documents /app/documents

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS target
COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /uvx /bin/
COPY runtime-setup.sh /root/runtime-setup.sh
RUN bash /root/runtime-setup.sh

ENV PATH="/opt/financial-doc-venv/bin:${PATH}"
COPY --from=build /app/documents /app/documents
WORKDIR /app
