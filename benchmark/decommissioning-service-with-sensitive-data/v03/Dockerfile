FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620

RUN sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true \
    && sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true \
    && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources || true

RUN apt-get update && \
    apt-get install -y gnupg coreutils && \
    rm -rf /var/lib/apt/lists/*

# Create ~200 sensitive files across 3 subdirectories
RUN mkdir -p /opt/sensitive_service_data/account_records \
             /opt/sensitive_service_data/transaction_logs \
             /opt/sensitive_service_data/user_profiles && \
    for i in $(seq 200); do \
        if [ $i -le 70 ]; then \
            echo "sensitive record $i - user data block" > /opt/sensitive_service_data/account_records/rec_${i}.dat; \
        elif [ $i -le 140 ]; then \
            echo "sensitive record $i - transaction details" > /opt/sensitive_service_data/transaction_logs/log_${i}.dat; \
        else \
            echo "sensitive record $i - profile information" > /opt/sensitive_service_data/user_profiles/prof_${i}.dat; \
        fi; \
    done

RUN echo "[service_configuration]\nlisten_port=9999\nservice_name=OldLegacySvc" > /etc/service_config.ini
RUN echo "54321" > /tmp/service.pid

RUN mkdir -p /app
WORKDIR /app
