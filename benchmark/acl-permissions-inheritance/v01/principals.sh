#!/bin/bash
set -euo pipefail

ensure_user() {
  id -u "$1" >/dev/null 2>&1 || useradd -m -s /bin/bash "$1"
}

groupadd -f editors
for user in alice bob runner; do ensure_user "$user"; done
usermod -aG editors alice
usermod -aG editors bob
gpasswd -d runner editors >/dev/null 2>&1 || true
