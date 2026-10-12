#!/bin/bash
set -euo pipefail

ensure_user() {
  id -u "$1" >/dev/null 2>&1 || useradd -m -s /bin/bash "$1"
}

groupadd -f research
for user in alice bob mallory; do ensure_user "$user"; done
usermod -aG research alice
gpasswd -d bob research >/dev/null 2>&1 || true
gpasswd -d mallory research >/dev/null 2>&1 || true
