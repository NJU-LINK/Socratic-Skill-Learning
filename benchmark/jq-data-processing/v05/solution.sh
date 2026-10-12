#!/bin/bash
set -euo pipefail

cd /app

filter='def trim_or_null: if . == null then null else (. | tostring | gsub("^\\s+|\\s+$"; "") | if . == "" then null else . end) end; [ .[] | select(.status == "active") | . as $u | (["display_name", "team", "phone", "last_login"] | map(select(($u[.] | trim_or_null) == null))) as $missing | select(($missing | length) > 0) | {user_id: .id, username, missing_fields: $missing, missing_field_count: ($missing | length), completeness_score: (((4 - ($missing | length)) / 4 * 100) | round), profile: {email: (.email | tostring | gsub("^\\s+|\\s+$"; "")), display_name: (.display_name | trim_or_null), team: (.team | trim_or_null), phone: (.phone | trim_or_null), last_login: (.last_login | trim_or_null | if . == null then null else .[0:10] end)}} ] | sort_by([-(.missing_field_count), .username])'

args=("--indent 2")

printf 'filter: %s\nargs:\n' "$(printf '%s' "$filter" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" > /app/jq_args.yaml
for arg in "${args[@]}"; do
    printf '  - %s\n' "$(printf '%s' "$arg" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" >> /app/jq_args.yaml
done

{
    printf 'jq'
    for arg in --indent 2; do
        printf ' %q' "$arg"
    done
    printf ' %q %q\n' "$filter" /app/users.json
} > /app/cmd.sh

jq --indent 2 "$filter" /app/users.json > /app/profile_completeness_audit.json
