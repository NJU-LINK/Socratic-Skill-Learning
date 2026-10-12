FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620

RUN sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true \
    && sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true \
    && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources || true \
    && apt-get update \
    && apt-get install -y --no-install-recommends coreutils gnupg xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir pytest==8.4.1

RUN printf '%s' 't-bench-passphrase' > /tmp/gpg_pass.key \
    && printf 'Key-Type: RSA\nKey-Length: 2048\nSubkey-Type: RSA\nSubkey-Length: 2048\nName-Real: Decommission Agent\nExpire-Date: 0\nPassphrase: %s\n%%commit\n' \
       "$(cat /tmp/gpg_pass.key)" > /tmp/gpg_params \
    && gpg --batch --generate-key /tmp/gpg_params \
    && rm /tmp/gpg_params \
    && echo "pinentry-mode loopback" >> /root/.gnupg/gpg.conf \
    && mkdir -p /opt/sensitive_service_data \
    && echo "This is highly secret user information." \
       > /opt/sensitive_service_data/user_secrets.txt \
    && echo "Backup config data." \
       > /opt/sensitive_service_data/backup_codes.dat \
    && printf '%s\n' \
       '[service_configuration]' \
       'listen_port=9999' \
       'service_name=OldLegacySvc' \
       > /etc/service_config.ini \
    && echo "54321" > /tmp/service.pid \
    && mkdir -p /app

WORKDIR /app
