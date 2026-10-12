#!/bin/bash
set -uo pipefail

cat > /app/solve.py << 'PYEOF'
import time
from flask import Flask, request, jsonify

app = Flask(__name__)

RATE_LIMIT = 5
WINDOW_SIZE = 10

rate_limit_data = {}

def get_client_ip():
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'

def get_rate_limit_state(ip):
    now = time.time()
    cutoff = now - WINDOW_SIZE
    timestamps = rate_limit_data.get(ip, [])
    timestamps = [t for t in timestamps if t > cutoff]
    rate_limit_data[ip] = timestamps
    return timestamps, now

@app.before_request
def check_rate_limit():
    if request.endpoint == 'reset':
        return

    ip = get_client_ip()
    timestamps, now = get_rate_limit_state(ip)

    if len(timestamps) >= RATE_LIMIT:
        oldest = timestamps[0]
        reset_seconds = int(WINDOW_SIZE - (now - oldest))
        if reset_seconds < 0:
            reset_seconds = 0
        return jsonify({
            "error": "Rate limit exceeded",
            "retry_after_seconds": reset_seconds
        }), 429

    timestamps.append(now)
    rate_limit_data[ip] = timestamps

@app.after_request
def add_headers(response):
    ip = get_client_ip()
    timestamps, now = get_rate_limit_state(ip)

    remaining = max(0, RATE_LIMIT - len(timestamps))
    if timestamps:
        oldest = timestamps[0]
        reset_seconds = int(WINDOW_SIZE - (now - oldest))
        if reset_seconds < 0:
            reset_seconds = 0
    else:
        reset_seconds = 0

    response.headers['X-RateLimit-Limit'] = str(RATE_LIMIT)
    response.headers['X-RateLimit-Remaining'] = str(remaining)
    response.headers['X-RateLimit-Reset'] = str(reset_seconds)
    return response

@app.route('/api/resource')
def resource():
    return jsonify({"status": "ok"})

@app.route('/api/reset', methods=['POST'])
def reset():
    rate_limit_data.clear()
    return jsonify({"status": "reset"})

if __name__ == '__main__':
    app.run(debug=True)
PYEOF
