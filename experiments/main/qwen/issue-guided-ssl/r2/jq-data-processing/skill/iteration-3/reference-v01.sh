#!/bin/bash
# Reference implementation for jq-data-processing family
# This script demonstrates the complete v01 solution pattern

set -e

INPUT_FILE="${1:-/app/users.json}"
OUTPUT_FILE="${2:-/app/verified_admin_contacts.json}"

jq --indent 2 '
[.[] |
  # Step 1: Filter by status
  select(.status == "active") |
  
  # Step 2: Build intermediate object with normalized fields
  {
    user_id: .id,
    username: .username,
    email: .email,
    email_domain: (.email | split("@")[1] | ascii_downcase),
    contact: "\(.username) <\(.email)>",
    phone: ((.phone // "") | gsub("^[[:space:]]+|[[:space:]]+$"; "") |
            if . == "" then "unknown" else . end),
    last_login: (.last_login | split("T")[0]),
    # Temporary fields for filtering (excluded from final output)
    _nr: (.roles // [] | map(gsub("^[[:space:]]+|[[:space:]]+$"; "") | ascii_downcase) | unique),
    _bd: (.blocked_domains // [] | map(gsub("^[[:space:]]+|[[:space:]]+$"; "") | ascii_downcase))
  } |
  
  # Step 3: Filter by privileged roles (admin or owner)
  select(._nr | any(. == "admin" or . == "owner")) |
  
  # Step 4: Exclude if email domain is in blocked list
  select(.email_domain as $ed | ._bd | index($ed) | not) |
  
  # Step 5: Build final output object (temporary fields excluded)
  {
    user_id: .user_id,
    username: .username,
    email: .email,
    email_domain: .email_domain,
    contact: .contact,
    phone: .phone,
    last_login: .last_login,
    account_summary: {
      role_count: (._nr | length),
      primary_role: (if (._nr | length) > 0 then ._nr[0] else null end),
      roles: ._nr
    }
  }
] |
# Step 6: Mixed-direction sort (stable-sort chaining)
sort_by(.username) | reverse |  # Secondary key: username descending
sort_by(.email_domain)          # Primary key: email_domain ascending
' "$INPUT_FILE" > "$OUTPUT_FILE"

echo "Transformed $(jq 'length' "$OUTPUT_FILE") records to $OUTPUT_FILE"
