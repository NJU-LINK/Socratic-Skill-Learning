#!/bin/bash
set -euo pipefail

cd /app

filter=$(cat <<'JQ'
map(
  . as $user
  | ($user.roles | length) as $role_count
  | ($user.last_login[0:10]) as $login_date
  | select($user.status == "active" and $role_count >= 2 and $login_date > "2024-09-15")
  | {
      user_id: $user.id,
      username: $user.username,
      email: $user.email,
      email_domain: ($user.email | split("@")[1]),
      last_login: $login_date,
      role_count: $role_count,
      primary_role: ($user.roles[0] // null)
    }
)
| sort_by([-(.last_login | strptime("%Y-%m-%d") | mktime), .username])
JQ
)

cat <<EOF > /app/jq_args.yaml
filter: |-
$(printf '%s\n' "$filter" | sed 's/^/  /')
args:
  - --indent 2
EOF

printf '%s\n' "jq --indent 2 '$filter' /app/users.json > /app/active_users_report.json" > /app/cmd.sh
chmod +x /app/cmd.sh

jq --indent 2 "$filter" /app/users.json > /app/active_users_report.json
