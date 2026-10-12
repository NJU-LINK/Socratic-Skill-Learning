#!/bin/bash
set -euo pipefail

cd /app

cat > /app/jq_args.yaml <<'EOF'
filter: |-
  def week_start:
    (.last_login | fromdateiso8601) as $ts
    | (($ts - (((($ts / 86400 | floor) + 3) % 7) * 86400)) | strftime("%Y-%m-%d"));

  map(
    select(.status == "active" or .status == "pending")
    | {
        week_start: week_start,
        user: {
          user_id: .id,
          username,
          email,
          team: (if .team == "" then "unassigned" else .team end),
          last_login: (.last_login[0:10]),
          role_count: (.roles | length),
          primary_role: (if (.roles | length) > 0 then .roles[0] else "none" end)
        }
      }
  )
  | sort_by([.week_start, .user.username])
  | group_by(.week_start)
  | map({
      week_start: .[0].week_start,
      user_count: length,
      users: (map(.user) | sort_by(.username))
    })
  | sort_by(.week_start)
  | reverse
args:
  - --indent 2
EOF

cat > /app/cmd.sh <<'EOF'
#!/bin/bash
jq --indent 2 '
def week_start:
  (.last_login | fromdateiso8601) as $ts
  | (($ts - (((($ts / 86400 | floor) + 3) % 7) * 86400)) | strftime("%Y-%m-%d"));

map(
  select(.status == "active" or .status == "pending")
  | {
      week_start: week_start,
      user: {
        user_id: .id,
        username,
        email,
        team: (if .team == "" then "unassigned" else .team end),
        last_login: (.last_login[0:10]),
        role_count: (.roles | length),
        primary_role: (if (.roles | length) > 0 then .roles[0] else "none" end)
      }
    }
)
| sort_by([.week_start, .user.username])
| group_by(.week_start)
| map({
    week_start: .[0].week_start,
    user_count: length,
    users: (map(.user) | sort_by(.username))
  })
| sort_by(.week_start)
| reverse
' /app/users.json > /app/weekly_activity_report.json
EOF

chmod +x /app/cmd.sh
bash /app/cmd.sh
