#!/bin/bash

set -euo pipefail

filter='map(
  select((.status == "pending") or (.status == "inactive"))
  | . as $user
  | ($user.username | ascii_downcase) as $normalized_username
  | select(($normalized_username | endswith("_tmp") | not) and ($normalized_username | endswith("_banned") | not))
  | {
      account: {
        user_id: $user.id,
        username: $normalized_username,
        email: $user.email,
        status: $user.status
      },
      access: {
        role_count: ($user.roles | length),
        primary_role: ($user.roles[0] // "none")
      }
    }

) | sort_by([-(.access.role_count), .account.username])'

printf '%s\n' "jq --indent 2 '$filter' /app/users.json > /app/review_queue.json" > /app/cmd.sh

{
  printf 'filter: |-\n'
  printf '%s\n' "$filter" | sed 's/^/  /'
  printf 'args:\n'
  printf '  - --indent 2\n'
} > /app/jq_args.yaml

jq --indent 2 "$filter" /app/users.json > /app/review_queue.json
