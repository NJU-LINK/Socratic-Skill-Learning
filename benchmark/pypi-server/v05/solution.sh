#!/bin/bash
set -euo pipefail

cd /app

cat <<'EOF' > /app/vectorops-src/src/vectorops/numeric.py
def coerce_values(values):
    if isinstance(values, (str, bytes)):
        raise TypeError("values must be an iterable of numbers")

    coerced = []
    for value in values:
        if not isinstance(value, (int, float)):
            raise TypeError("values must contain only ints or floats")
        coerced.append(value)

    if not coerced:
        raise ValueError("values must not be empty")

    return tuple(coerced)


def ensure_same_length(left, right):
    if len(left) != len(right):
        raise ValueError("vectors must have the same length")
EOF

cat <<'EOF' > /app/vectorops-src/src/vectorops/models.py
from .numeric import coerce_values, ensure_same_length


class Vector:
    def __init__(self, values):
        self.values = coerce_values(values)

    def magnitude_squared(self):
        return sum(value * value for value in self.values)

    def dot(self, other):
        other_values = coerce_values(other.values if isinstance(other, Vector) else other)
        ensure_same_length(self.values, other_values)
        return sum(left * right for left, right in zip(self.values, other_values))
EOF

cat <<'EOF' > /app/vectorops-src/src/vectorops/api.py
from .models import Vector
from .numeric import coerce_values, ensure_same_length


def dotproduct(left, right):
    left_values = coerce_values(left)
    right_values = coerce_values(right)
    ensure_same_length(left_values, right_values)
    return sum(left_value * right_value for left_value, right_value in zip(left_values, right_values))
EOF

rm -f /srv/pypi/packages/vectorops-0.1.0* /tmp/vectorops-dist/vectorops-0.1.0*
python3 -m build /app/vectorops-src --wheel --outdir /tmp/vectorops-dist
cp /tmp/vectorops-dist/vectorops-0.1.0-py3-none-any.whl /srv/pypi/packages/

mkdir -p /srv/pypi/simple/vectorops

cat <<'EOF' > /srv/pypi/simple/index.html
<html><body>
<a href="vectorops/">vectorops</a>
</body></html>
EOF

cat <<'EOF' > /srv/pypi/simple/vectorops/index.html
<html><body>
<a href="../../packages/vectorops-0.1.0-py3-none-any.whl">vectorops-0.1.0-py3-none-any.whl</a>
</body></html>
EOF

if [ -f /tmp/pypi-server.pid ]; then
    old_pid=$(cat /tmp/pypi-server.pid || true)
    if [ -n "${old_pid}" ] && kill -0 "$old_pid" 2>/dev/null; then
        kill "$old_pid"
    fi
fi

nohup python3 -m http.server 8080 --directory /srv/pypi >/tmp/pypi-server.log 2>&1 &
server_pid=$!
echo "$server_pid" >/tmp/pypi-server.pid

for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS http://localhost:8080/simple/vectorops/ >/dev/null 2>&1; then
        exit 0
    fi
    sleep 1
done

echo "Local package index failed to start" >&2
exit 1
