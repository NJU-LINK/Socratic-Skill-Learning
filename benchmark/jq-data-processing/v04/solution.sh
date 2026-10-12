#!/bin/bash
set -euo pipefail

cat > /app/cmd.sh <<'EOF'
jq --indent 2 '
def approved_domains: ["example.com", "company.org", "ops.net", "portal.io"];

[
  .[]
  | (.email | split("@")[1] | ascii_downcase) as $domain
  | select(.status == "active" and (approved_domains | index($domain)))
  | {
      domain: $domain,
      username: .username,
      email: .email,
      last_login: (.last_login | split("T")[0]),
      primary_role: (if (.roles | length) > 0 then .roles[0] else "none" end),
      privileged: ((.roles | index("admin")) != null or (.roles | index("owner")) != null)
    }
]
| sort_by(.domain)
| group_by(.domain)
| map({
    domain: .[0].domain,
    metrics: {
      user_count: length,
      privileged_user_count: (map(select(.privileged)) | length)
    },
    recent_users: (
      sort_by(-(.last_login | strptime("%Y-%m-%d") | mktime), .username)
      | map({
          username,
          email,
          last_login,
          primary_role
        })[:3]
    )
  })
| sort_by(-(.metrics.user_count), .domain)
' /app/users.json > /app/domain_activity_rollup.json
EOF

chmod +x /app/cmd.sh
bash /app/cmd.sh

cat > /app/jq_args.yaml <<'EOF'
filter: |
  def approved_domains: ["example.com", "company.org", "ops.net", "portal.io"];

  [
    .[]
    | (.email | split("@")[1] | ascii_downcase) as $domain
    | select(.status == "active" and (approved_domains | index($domain)))
    | {
        domain: $domain,
        username: .username,
        email: .email,
        last_login: (.last_login | split("T")[0]),
        primary_role: (if (.roles | length) > 0 then .roles[0] else "none" end),
        privileged: ((.roles | index("admin")) != null or (.roles | index("owner")) != null)
      }
  ]
  | sort_by(.domain)
  | group_by(.domain)
  | map({
      domain: .[0].domain,
      metrics: {
        user_count: length,
        privileged_user_count: (map(select(.privileged)) | length)
      },
      recent_users: (
        sort_by(-(.last_login | strptime("%Y-%m-%d") | mktime), .username)
        | map({
            username,
            email,
            last_login,
            primary_role
          })[:3]
      )
    })
  | sort_by(-(.metrics.user_count), .domain)
args:
  - "--indent 2"
EOF
