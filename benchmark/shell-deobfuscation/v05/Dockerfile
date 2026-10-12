FROM python:3.11-slim AS build
WORKDIR /app
COPY generate_payload.py /app/generate_payload.py
RUN python3 /app/generate_payload.py \
    && test -s /app/suspicious_script.sh \
    && chmod +x /app/suspicious_script.sh

FROM python:3.11-slim AS target
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources || true \
    && apt-get -o Acquire::Retries=3 update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends xxd \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest==8.4.1
COPY --from=build /app/suspicious_script.sh /app/suspicious_script.sh
COPY --from=build /app/suspicious_script.sh /opt/task-input/suspicious_script.sh
RUN useradd -m agent \
    && mkdir -p /tests /oracle /installed-agent /agent-logs /logs \
    && chmod -R 777 /installed-agent \
    && chmod 555 /opt/task-input \
    && chmod 444 /opt/task-input/suspicious_script.sh \
    && chown -R agent:agent /app
WORKDIR /app
USER agent
