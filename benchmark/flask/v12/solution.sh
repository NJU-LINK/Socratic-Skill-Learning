#!/bin/bash
set -uo pipefail

cat > /app/solve.py << 'PYEOF'
import string
import random
from datetime import datetime, timezone
from flask import Flask, jsonify, request, redirect

app = Flask(__name__)

url_map = {}


def generate_code():
    chars = string.ascii_letters + string.digits
    while True:
        code = ''.join(random.choices(chars, k=6))
        if code not in url_map:
            return code


@app.route('/shorten', methods=['POST'])
def shorten():
    data = request.get_json(silent=True)
    if not data or 'url' not in data:
        return jsonify({'error': 'URL is required'}), 400
    url = data['url']
    if not (url.startswith('http://') or url.startswith('https://')):
        return jsonify({'error': 'Invalid URL'}), 400
    code = generate_code()
    now = datetime.now(timezone.utc).isoformat()
    url_map[code] = {
        'original_url': url,
        'visits': 0,
        'created_at': now,
    }
    return jsonify({'short_code': code, 'original_url': url}), 201


@app.route('/stats/<short_code>')
def get_stats(short_code):
    entry = url_map.get(short_code)
    if not entry:
        return jsonify({'error': 'Short code not found'}), 404
    return jsonify({
        'short_code': short_code,
        'original_url': entry['original_url'],
        'visits': entry['visits'],
        'created_at': entry['created_at'],
    })


@app.route('/popular')
def popular():
    sorted_codes = sorted(
        url_map.items(), key=lambda x: x[1]['visits'], reverse=True
    )[:5]
    result = [
        {
            'short_code': code,
            'original_url': entry['original_url'],
            'visits': entry['visits'],
        }
        for code, entry in sorted_codes
    ]
    return jsonify(result)


@app.route('/<short_code>')
def redirect_to_url(short_code):
    entry = url_map.get(short_code)
    if not entry:
        return jsonify({'error': 'Short code not found'}), 404
    entry['visits'] += 1
    return redirect(entry['original_url'], 302)


if __name__ == '__main__':
    app.run(debug=True)
PYEOF
