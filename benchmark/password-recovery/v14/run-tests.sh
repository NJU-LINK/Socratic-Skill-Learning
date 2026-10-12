#!/bin/bash
set -e

cd "$(dirname "$0")"

# Fix apt sources for HTTP proxy that cannot forward plain HTTP
sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true
sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true

apt-get update -qq 2>/dev/null
apt-get install -y -qq python3-pytest 2>/dev/null

python3 -m pytest . -v
