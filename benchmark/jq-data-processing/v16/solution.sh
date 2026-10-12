#!/bin/bash
set -euo pipefail

filter='[
  .[]
  | select(.status == "active" or .status == "pending")
  | {
      month: (.last_login[0:7]),
      user: {
        user_id: .id,
        username: .username,
        has_roles: ((.roles | length) > 0),
        primary_role: (.roles[0] // null)
      }
    }
] 
| sort_by(.month, .user.username)
| group_by(.month)
| map({
    month: .[0].month,
    total_users: length,
    users: (map(.user) | sort_by(.username))
  })'

jq --indent 2 "$filter" /app/users.json > /app/monthly_activity_rollup.json

cat > /app/cmd.sh <<EOF
#!/bin/bash
set -euo pipefail

jq --indent 2 '$filter' /app/users.json > /app/monthly_activity_rollup.json
EOF

cat > /app/jq_args.yaml <<'EOF'
filter: |-
  [
    .[]
    | select(.status == "active" or .status == "pending")
    | {
        month: (.last_login[0:7]),
        user: {
          user_id: .id,
          username: .username,
          has_roles: ((.roles | length) > 0),
          primary_role: (.roles[0] // null)
        }
      }
  ]
  | sort_by(.month, .user.username)
  | group_by(.month)
  | map({
      month: .[0].month,
      total_users: length,
      users: (map(.user) | sort_by(.username))
    })
args:
  - --indent 2
EOF

chmod +x /app/cmd.sh
