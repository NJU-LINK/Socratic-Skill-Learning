#!/bin/bash
set -euo pipefail

FILTER=$(cat <<'JQ'
def normalize_department:
  if . == null then
    "Unassigned"
  else
    (tostring | gsub("^[[:space:]]+|[[:space:]]+$"; "")) as $trimmed
    | if $trimmed == "" then
        "Unassigned"
      else
        $trimmed
        | gsub("[_-]+"; " ")
        | gsub("[[:space:]]+"; " ")
        | split(" ")
        | map(
            ascii_downcase as $word
            | if ($word | length) == 0 then
                $word
              else
                ($word[0:1] | ascii_upcase) + $word[1:]
              end
          )
        | join(" ")
      end
  end;

def sortable_ts:
  gsub("[-:TZ]"; "") | tonumber;

map(
  select(.status == "active")
  | select(.last_login >= "2025-01-01T00:00:00Z")
  | select((.roles | length) >= 2)
  | . + {normalized_department: (.department | normalize_department)}
)
| group_by(.normalized_department)
| map(
    sort_by([-(.last_login | sortable_ts), .username]) as $users
    | {
        department: $users[0].normalized_department,
        member_count: ($users | length),
        usernames: ($users | map(.username)),
        members: (
          $users
          | map({
              user_id: .id,
              username,
              email,
              last_login: (.last_login | split("T")[0]),
              role_count: (.roles | length),
              primary_role: (.roles[0] // null)
            })
        )
      }
  )
| sort_by(.department)
JQ
)

{
  FILTER_YAML=$(printf '%s' "$FILTER" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
  printf 'filter: %s\n' "$FILTER_YAML"
  printf 'args:'"\n"
  printf '  - "--indent 2"'"\n"
} > /app/jq_args.yaml

cat > /app/cmd.sh <<EOF
jq --indent 2 '$FILTER' /app/users.json > /app/team_activity_snapshot.json
EOF

jq --indent 2 "$FILTER" /app/users.json > /app/team_activity_snapshot.json
