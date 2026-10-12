FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /uvx /bin/
COPY runtime-setup.sh /root/runtime-setup.sh
RUN bash /root/runtime-setup.sh

ENV PATH="/opt/financial-doc-venv/bin:${PATH}"

FROM runtime AS build

RUN uv pip install --python /opt/financial-doc-venv/bin/python \
    reportlab==4.4.3

COPY generate_documents.py randomize_filenames.py /root/
WORKDIR /root
RUN python3 /root/generate_documents.py \
    && python3 /root/randomize_filenames.py

FROM runtime AS target
COPY --from=build /app/documents /app/documents
WORKDIR /app
