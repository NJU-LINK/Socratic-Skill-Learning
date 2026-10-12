#!/bin/bash
set -euo pipefail

ensure_user() {
  id -u "$1" >/dev/null 2>&1 || useradd -m -s /bin/bash "$1"
}

groupadd -f research
for user in alice bob carol; do
  ensure_user "$user"
  usermod -aG research "$user"
done
