#!/bin/bash
set -euo pipefail

FILTER='[.[] | select(.status == "active") | {login_month: .last_login[0:7], username, primary_role: (.roles[0]? // null), role_count: (.roles | length)}] | group_by(.login_month) | map({login_month: .[0].login_month, active_user_count: length, avg_role_count: ((((map(.role_count) | add) / length) * 100 | round) / 100), top_users: (sort_by([-(.role_count), .username]) | .[:3] | map({username, primary_role, role_count}))}) | sort_by(.login_month) | reverse'
CMD="jq --indent 2 '$FILTER' /app/users.json > /app/monthly_login_rollup.json"

bash -lc "$CMD"

cat <<EOF > /app/cmd.sh
#!/bin/bash
$CMD
EOF

cat <<'EOF' > /app/jq_args.yaml
filter: >-
  [.[] | select(.status == "active") | {login_month: .last_login[0:7], username, primary_role: (.roles[0]? // null), role_count: (.roles | length)}] | group_by(.login_month) | map({login_month: .[0].login_month, active_user_count: length, avg_role_count: ((((map(.role_count) | add) / length) * 100 | round) / 100), top_users: (sort_by([-(.role_count), .username]) | .[:3] | map({username, primary_role, role_count}))}) | sort_by(.login_month) | reverse
args:
  - --indent 2
EOF

chmod +x /app/cmd.sh
