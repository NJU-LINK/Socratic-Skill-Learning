#!/bin/bash
set -euo pipefail

FILTER='[
  .[]
  | select(.status == "active" or .status == "pending")
  | . as $user
  | ((.roles // []) | map(select(type == "string")) | unique[]) as $role
  | {
      role: $role,
      member: {
        user_id: $user.id,
        username: ($user.username | ascii_downcase),
        email: $user.email,
        last_login: (
          if ($user.last_login | type) == "string" then
            ($user.last_login | gsub("^\\s+|\\s+$"; "") | if . == "" then null else split("T")[0] end)
          else
            null
          end
        )
      }
    }
]
| group_by(.role)
| map({
    role: .[0].role,
    member_count: length,
    members: (map(.member) | sort_by([.username, .user_id]))
  })
| sort_by([-(.member_count), .role])'

ARGS=("--indent 2")

{
  printf 'filter: |-\n'
  while IFS= read -r line; do
    printf '  %s\n' "$line"
  done <<< "$FILTER"
  printf 'args:\n'
  for arg in "${ARGS[@]}"; do
    printf '  - %s\n' "$arg"
  done
} > /app/jq_args.yaml

CMD=$(printf 'jq %s %q /app/users.json > /app/active_users_report.json' "${ARGS[*]}" "$FILTER")
printf '%s\n' "$CMD" > /app/cmd.sh

eval "$CMD"
