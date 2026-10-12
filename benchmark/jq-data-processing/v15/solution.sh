#!/bin/bash
set -euo pipefail

FILTER='def latest_user: max_by(.last_login);
  def role_count_avg: (map(.roles | length) | add / length);
  map(select(.status != null))
  | group_by(.status)
  | map(select(length >= $min_count))
  | map({
      status: .[0].status,
      user_count: length,
      average_role_count: role_count_avg,
      most_recent_user: (latest_user | {
        user_id: .id,
        username: .username,
        email: .email,
        last_login: (.last_login | split("T")[0]),
        primary_role: (.roles[0] // null)
      })
    })
  | sort_by(.status)'

printf '%s\n' '#!/bin/bash' "jq --argjson min_count 150 '$FILTER' /app/users.json > /app/status_dashboard.json" > /app/cmd.sh

cat > /app/jq_args.yaml <<'EOF'
filter: |
  def latest_user: max_by(.last_login);
  def role_count_avg: (map(.roles | length) | add / length);
  map(select(.status != null))
  | group_by(.status)
  | map(select(length >= $min_count))
  | map({
      status: .[0].status,
      user_count: length,
      average_role_count: role_count_avg,
      most_recent_user: (latest_user | {
        user_id: .id,
        username: .username,
        email: .email,
        last_login: (.last_login | split("T")[0]),
        primary_role: (.roles[0] // null)
      })
    })
  | sort_by(.status)
args:
  - --argjson min_count 150
EOF

jq --argjson min_count 150 "$FILTER" /app/users.json > /app/status_dashboard.json
