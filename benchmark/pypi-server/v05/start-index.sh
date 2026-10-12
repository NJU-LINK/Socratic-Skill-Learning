#!/bin/sh
set -eu

pypi-server run -p 8080 /srv/pypi/packages >/tmp/pypi-server.log 2>&1 &
server_pid=$!
echo "$server_pid" >/tmp/pypi-server.pid

for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS http://localhost:8080/simple/ >/dev/null 2>&1; then
        exit 0
    fi
    sleep 1
done

echo "PyPI index server failed to start" >&2
exit 1
