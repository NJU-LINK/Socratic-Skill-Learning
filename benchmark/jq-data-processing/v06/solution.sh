#!/bin/bash
set -euo pipefail

cat > /app/cmd.sh <<EOF
#!/bin/bash
set -euo pipefail
jq --indent 2 '
  [
    .[]
    | .normalized_plan = ((.plan // "") | ascii_downcase)
    | .distinct_roles = ((.roles // []) | unique | sort)
    | select(
        (.status == "active" or .status == "pending")
        and (.normalized_plan == "pro" or .normalized_plan == "enterprise")
        and .last_login >= "2024-09-01T00:00:00Z"
      )
    | {
        _sort_plan: .normalized_plan,
        _sort_login_epoch: (.last_login | fromdateiso8601),
        user_id: .id,
        username: .username,
        email: .email,
        account_key: "\(.username)#\(.id)",
        last_login_date: (.last_login | split("T")[0]),
        phone: (if (.phone // "") == "" then "unknown" else .phone end),
        role_count: (.distinct_roles | length),
        roles: .distinct_roles,
        plan_flags: {
          normalized_plan: .normalized_plan,
          is_enterprise: (.normalized_plan == "enterprise")
        }
      }
  ]
  | sort_by([._sort_plan, -._sort_login_epoch, .username])
  | map(del(._sort_plan, ._sort_login_epoch))
' /app/users.json > /app/recent_premium_users_report.json
EOF

cat > /app/jq_args.yaml <<'EOF'
filter: |
  [
    .[]
    | .normalized_plan = ((.plan // "") | ascii_downcase)
    | .distinct_roles = ((.roles // []) | unique | sort)
    | select(
        (.status == "active" or .status == "pending")
        and (.normalized_plan == "pro" or .normalized_plan == "enterprise")
        and .last_login >= "2024-09-01T00:00:00Z"
      )
    | {
        _sort_plan: .normalized_plan,
        _sort_login_epoch: (.last_login | fromdateiso8601),
        user_id: .id,
        username: .username,
        email: .email,
        account_key: "\(.username)#\(.id)",
        last_login_date: (.last_login | split("T")[0]),
        phone: (if (.phone // "") == "" then "unknown" else .phone end),
        role_count: (.distinct_roles | length),
        roles: .distinct_roles,
        plan_flags: {
          normalized_plan: .normalized_plan,
          is_enterprise: (.normalized_plan == "enterprise")
        }
      }
  ]
  | sort_by([._sort_plan, -._sort_login_epoch, .username])
  | map(del(._sort_plan, ._sort_login_epoch))
args:
  - --indent
  - "2"
EOF

chmod +x /app/cmd.sh
bash /app/cmd.sh
