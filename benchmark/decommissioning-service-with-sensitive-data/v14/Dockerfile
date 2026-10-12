FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620

RUN sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true \
    && sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true \
    && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources || true

RUN apt-get update \
    && apt-get install -y --no-install-recommends gnupg coreutils e2fsprogs \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir pytest==8.4.1

RUN mkdir -p /opt/sensitive_service_data /var/log/decommissioned_svc \
    && echo "This is highly secret user information." > /opt/sensitive_service_data/user_secrets.txt \
    && echo "Backup config data." > /opt/sensitive_service_data/backup_codes.dat \
    && printf '[service_configuration]\nlisten_port=9999\nservice_name=OldLegacySvc\n' > /etc/service_config.ini \
    && printf '2024-01-15 10:30:00 - Service initialized\n' > /var/log/decommissioned_svc/service.log \
    && printf 'ERROR: Failed to authenticate user session\n' > /var/log/decommissioned_svc/error.log \
    && touch /run/decommissioned_svc.sock

RUN printf '#!/bin/bash\nset -e\npython3 -m http.server 9999 --bind 127.0.0.1 --directory /opt/sensitive_service_data >>/var/log/decommissioned_svc/service.log 2>&1 &\nservice_pid=$!\nprintf "%%s\\n" "$service_pid" > /tmp/decommissioned_svc.pid\nexec "$@"\n' > /usr/local/bin/task-entrypoint.sh \
    && chmod +x /usr/local/bin/task-entrypoint.sh

WORKDIR /app
ENTRYPOINT ["/usr/local/bin/task-entrypoint.sh"]
