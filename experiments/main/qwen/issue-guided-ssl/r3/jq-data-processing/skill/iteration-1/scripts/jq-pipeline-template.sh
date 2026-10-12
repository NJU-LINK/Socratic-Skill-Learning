#!/usr/bin/env bash
# jq-pipeline-template.sh
# Reusable template for jq data-processing tasks in this family.
# Adapt the FILTER variable for each specific task.

set -euo pipefail

INPUT_FILE="${1:?Usage: $0 <input.json> <output.json>}"
OUTPUT_FILE="${2:?Usage: $0 <input.json> <output.json>}"

# The jq filter - adapt for each task
# Key patterns:
#   1. def normalize at top
#   2. Compute intermediate normalized values with `as` bindings
#   3. select() for filtering
#   4. Build output object
#   5. Wrap in [...] to collect array
#   6. Sort with stable-sort chaining for mixed directions
FILTER='
def normalize: gsub("^\\s+|\\s+$"; "") | ascii_downcase;
[
  .[] |
  # --- Stage 1: Normalize intermediate values ---
  (.email | split("@")[1] | ascii_downcase) as $email_domain |
  (.blocked_domains // [] | map(normalize)) as $blocked |
  (.roles // [] | map(normalize) | unique) as $norm_roles |

  # --- Stage 2: Filter records ---
  select(.status == "active") |
  select($blocked | index($email_domain) | not) |
  select($norm_roles | any(. == "admin" or . == "owner")) |

  # --- Stage 3: Reshape output fields ---
  (.phone // "" | normalize) as $trimmed_phone |
  {
    user_id: .id,
    username: .username,
    email: .email,
    email_domain: $email_domain,
    contact: "\(.username) <\(.email)>",
    phone: (if $trimmed_phone == "" then "unknown" else $trimmed_phone end),
    last_login: (.last_login[0:10]),
    account_summary: {
      role_count: ($norm_roles | length),
      primary_role: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end),
      roles: $norm_roles
    }
  }
]
# --- Stage 4: Sort (secondary first for mixed directions) ---
| sort_by(.username) | reverse
| sort_by(.email_domain)
'

jq --indent 2 "$FILTER" "$INPUT_FILE" > "$OUTPUT_FILE"
echo "Wrote $(jq 'length' "$OUTPUT_FILE") records to $OUTPUT_FILE"
