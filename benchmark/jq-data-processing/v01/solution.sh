#!/bin/bash
set -euo pipefail

FILTER=$(cat <<'JQ'
def norm_role: tostring | gsub("^[[:space:]]+|[[:space:]]+$"; "") | ascii_downcase;
def norm_domain: split("@")[-1] | ascii_downcase;
def norm_blocked: tostring | gsub("^[[:space:]]+|[[:space:]]+$"; "") | ascii_downcase;
def norm_phone:
  if . == null then
    "unknown"
  else
    ((tostring | gsub("^[[:space:]]+|[[:space:]]+$"; "")) as $p | if $p == "" then "unknown" else $p end)
  end;

map(
  (.roles | map(norm_role) | unique | sort) as $roles
  | (.email | norm_domain) as $email_domain
  | (.blocked_domains | map(norm_blocked)) as $blocked
  | select(.status == "active")
  | select(($roles | any(. == "admin" or . == "owner")))
  | select(($blocked | index($email_domain)) == null)
  | {
      user_id: .id,
      username,
      email,
      email_domain: $email_domain,
      contact: "\(.username) <\(.email)>",
      phone: (.phone | norm_phone),
      last_login: (.last_login | split("T")[0]),
      account_summary: {
        role_count: ($roles | length),
        primary_role: ($roles[0] // null),
        roles: $roles
      }
    }
)
| sort_by(.username) | reverse
| sort_by(.email_domain)
JQ
)

{
  printf 'filter: |-\n'
  printf '%s\n' "$FILTER" | sed 's/^/  /'
  printf 'args:\n'
  printf '  - --indent 2\n'
} > /app/jq_args.yaml

cat > /app/cmd.sh <<EOF
jq --indent 2 '$FILTER' /app/users.json > /app/verified_admin_contacts.json
EOF

jq --indent 2 "$FILTER" /app/users.json > /app/verified_admin_contacts.json
