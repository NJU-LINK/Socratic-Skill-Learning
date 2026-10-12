FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620

RUN sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true \
    && sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true \
    && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources || true

RUN apt-get update \
    && apt-get install -y --no-install-recommends gnupg coreutils \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir pytest==8.4.1

RUN mkdir -p /opt/sensitive_service_data \
    && echo "This is highly secret user information." > /opt/sensitive_service_data/user_secrets.txt \
    && echo "Backup config data." > /opt/sensitive_service_data/backup_codes.dat \
    && printf '[service_configuration]\nlisten_port=9999\nservice_name=OldLegacySvc\n' > /etc/service_config.ini

RUN printf '#!/bin/bash\nexec -a legacy_service sleep infinity\n' > /usr/local/bin/legacy_service.sh \
    && chmod +x /usr/local/bin/legacy_service.sh \
    && mkdir -p /etc/systemd/system /var/log/legacy_service \
    && printf '[Unit]\nDescription=Legacy Service\n\n[Service]\nExecStart=/usr/local/bin/legacy_service.sh\n' > /etc/systemd/system/legacy_service.service \
    && printf '[2024-01-15 10:30:00] Service started\n' > /var/log/legacy_service/service.log \
    && printf 'ERROR: Failed to connect to database\n' > /var/log/legacy_service/error.log \
    && touch /run/legacy_service.sock

RUN printf '#!/bin/bash\nset -e\n/usr/local/bin/legacy_service.sh &\nservice_pid=$!\nprintf "%%s\\n" "$service_pid" > /tmp/service.pid\nprintf "%%s\\n" "$service_pid" > /run/legacy_service.pid\nexec "$@"\n' > /usr/local/bin/task-entrypoint.sh \
    && chmod +x /usr/local/bin/task-entrypoint.sh

WORKDIR /app
ENTRYPOINT ["/usr/local/bin/task-entrypoint.sh"]
