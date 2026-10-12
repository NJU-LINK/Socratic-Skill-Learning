FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS build
COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /uvx /bin/

COPY document_specs.json generate_documents.py randomize_filenames.py /root/
WORKDIR /root
RUN mkdir -p /tmp/original_documents /app/documents \
    && uv run /root/generate_documents.py /root/document_specs.json /tmp/original_documents \
    && uv run /root/randomize_filenames.py /tmp/original_documents /app/documents

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS target
COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /uvx /bin/
COPY runtime-setup.sh /root/runtime-setup.sh
RUN bash /root/runtime-setup.sh

ENV PATH="/opt/financial-doc-venv/bin:${PATH}"
COPY --from=build /app/documents /app/documents
WORKDIR /app
