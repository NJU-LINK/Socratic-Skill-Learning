#!/bin/bash
set -euo pipefail

ensure_user() {
  id -u "$1" >/dev/null 2>&1 || useradd -m -s /bin/bash "$1"
}

groupadd -f research
for user in alice collaborator reviewer; do ensure_user "$user"; done
usermod -aG research alice
usermod -aG research collaborator
gpasswd -d reviewer research >/dev/null 2>&1 || true
