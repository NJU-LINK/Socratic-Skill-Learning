#!/bin/bash
# Smoke test for jq snippets in SKILL.md and references/jq-idioms.md
# Verifies all fenced jq code blocks compile and produce expected output

set -e

echo "=== Testing IN membership (correct comma syntax) ==="
jq -n '"admin" | IN("admin", "owner", "user")' | grep -q "true" && echo "PASS: IN with commas works"

echo "=== Testing IN membership (incorrect semicolon syntax fails) ==="
if jq -n '"admin" | IN("admin"; "owner"; "user")' 2>/dev/null; then
    echo "FAIL: IN with semicolons should fail"
    exit 1
else
    echo "PASS: IN with semicolons correctly fails"
fi

echo "=== Testing existential quantification (any) ==="
jq -n '{"roles": ["editor", "admin"]} | any(.roles[]; . == "admin")' | grep -q "true" && echo "PASS: any() with matching role"
jq -n '{"roles": ["editor", "user"]} | any(.roles[]; . == "admin")' | grep -q "false" && echo "PASS: any() with no matching role"

echo "=== Testing universal quantification (all) ==="
jq -n '{"roles": ["admin", "admin"]} | all(.roles[]; . == "admin")' | grep -q "true" && echo "PASS: all() with all matching"
jq -n '{"roles": ["admin", "user"]} | all(.roles[]; . == "admin")' | grep -q "false" && echo "PASS: all() with non-matching"

echo "=== Testing string normalization (trim + ascii_downcase) ==="
jq -n 'def trim: gsub("^\\s+|\\s+$"; ""); def norm: trim | ascii_downcase; "  ADMIN  " | norm' | grep -q '"admin"' && echo "PASS: trim and norm"

echo "=== Testing date extraction (ymd) ==="
jq -n 'def ymd: split("T")[0]; "2026-03-16T05:01:40.829540Z" | ymd' | grep -q '"2026-03-16"' && echo "PASS: ymd extraction"

echo "=== Testing mixed-direction sort ==="
jq -n '[
    {"domain": "a.com", "user": "charlie"},
    {"domain": "a.com", "user": "alice"},
    {"domain": "b.com", "user": "bob"}
] | group_by(.domain) | map(sort_by(.user) | reverse) | add |
    map(.user) == ["charlie", "alice", "bob"]' | grep -q "true" && echo "PASS: mixed-direction sort"

echo "=== Testing contains caveat (substring match) ==="
jq -n '"foobar" | contains("bar")' | grep -q "true" && echo "PASS: contains does substring match on strings"

echo "=== Testing optional field handling ==="
jq -n '{"phone": "  123-456  "} | ((.phone // "") | gsub("^\\s+|\\s+$"; "") | if . == "" then "unknown" else . end)' | grep -q '"123-456"' && echo "PASS: trim with value"
jq -n '{} | ((.phone // "") | gsub("^\\s+|\\s+$"; "") | if . == "" then "unknown" else . end)' | grep -q '"unknown"' && echo "PASS: default for missing field"
jq -n '{"phone": "   "} | ((.phone // "") | gsub("^\\s+|\\s+$"; "") | if . == "" then "unknown" else . end)' | grep -q '"unknown"' && echo "PASS: default for blank field"

echo "=== Testing unique on normalized roles ==="
jq -n '{"roles": ["ADMIN ", " admin", "Editor"]} | [.roles[] | gsub("^\\s+|\\s+$"; "") | ascii_downcase] | unique' | jq -e 'length == 2 and .[0] == "admin" and .[1] == "editor"' && echo "PASS: normalize then unique"

echo "=== Testing select(generator) duplication bug ==="
# Demonstrate that bare generator in select duplicates rows
# User 1 has 2 matching roles (admin, owner) -> emits TWICE
# User 2 has 0 matching roles -> filtered out
# Expected: 2 outputs (demonstrating duplication of user 1)
COUNT=$(jq -n '[
    {"id": 1, "roles": ["admin", "owner"]},
    {"id": 2, "roles": ["user"]}
] | [.[] | select(.roles[] | . == "admin" or . == "owner")] | length')
if [ "$COUNT" -eq 2 ]; then
    echo "PASS: select(generator) produces 2 outputs (demonstrates duplication of user with multiple matching roles)"
else
    echo "FAIL: Expected 2 outputs from select(generator), got $COUNT"
    exit 1
fi

# Demonstrate correct behavior with any()
COUNT=$(jq -n '[
    {"id": 1, "roles": ["admin", "owner"]},
    {"id": 2, "roles": ["user"]}
] | [.[] | select(any(.roles[]; . == "admin" or . == "owner"))] | length')
if [ "$COUNT" -eq 1 ]; then
    echo "PASS: select(any()) produces 1 output (correct)"
else
    echo "FAIL: Expected 1 output from select(any()), got $COUNT"
    exit 1
fi

echo ""
echo "=== Testing jq_args.yaml structural validation ==="

# Create temp directory for fixtures
TMPDIR=$(mktemp -d)

# Correct shape: flag and value together
cat > "$TMPDIR/correct.yaml" << 'EOF'
filter: "."
args:
  - "--indent 2"
  - "--raw-output"
EOF

# Wrong shape: split flag and value
cat > "$TMPDIR/wrong.yaml" << 'EOF'
filter: "."
args:
  - "--indent"
  - "2"
EOF

# Empty args (valid)
cat > "$TMPDIR/empty.yaml" << 'EOF'
filter: "."
args: []
EOF

# Structural validator function
validate_yaml() {
    yq -j . "$1" | jq -e '
        (keys | sort == ["args","filter"]) and
        (.filter | type == "string") and
        (.args | type == "array") and
        (.args | all(type == "string" and startswith("-")))
    ' >/dev/null 2>&1
}

if validate_yaml "$TMPDIR/correct.yaml"; then
    echo "PASS: Correct shape args: [\"--indent 2\"] validates"
else
    echo "FAIL: Correct shape should validate"
    rm -rf "$TMPDIR"
    exit 1
fi

if ! validate_yaml "$TMPDIR/wrong.yaml" 2>/dev/null; then
    echo "PASS: Wrong shape args: [\"--indent\", \"2\"] correctly fails validation"
else
    echo "FAIL: Wrong shape should fail validation"
    rm -rf "$TMPDIR"
    exit 1
fi

if validate_yaml "$TMPDIR/empty.yaml"; then
    echo "PASS: Empty args: [] validates"
else
    echo "FAIL: Empty args should validate"
    rm -rf "$TMPDIR"
    exit 1
fi

rm -rf "$TMPDIR"

echo ""
echo "=== Testing cmd.sh structural validation ==="

# Create temp directory for cmd.sh fixtures
TMPDIR=$(mktemp -d)

# Correct cmd.sh with absolute paths
cat > "$TMPDIR/correct_cmd.sh" << 'EOF'
jq --indent 2 'def trim: gsub("^\\s+|\\s+$"; ""); .' /app/users.json > /app/verified_admin_contacts.json
EOF

# Wrong cmd.sh with relative paths
cat > "$TMPDIR/wrong_cmd.sh" << 'EOF'
jq --indent 2 'def trim: gsub("^\\s+|\\s+$"; ""); .' users.json > verified_admin_contacts.json
EOF

# cmd.sh structural validator
check_cmd() {
    grep -qE '^jq ' "$1" && \
    grep -qF '/app/users.json' "$1" && \
    grep -qF '/app/verified_admin_contacts.json' "$1" && \
    grep -qE '> /app/[^ ]+$' "$1"
}

if check_cmd "$TMPDIR/correct_cmd.sh"; then
    echo "PASS: Correct cmd.sh with absolute paths validates"
else
    echo "FAIL: Correct cmd.sh should validate"
    rm -rf "$TMPDIR"
    exit 1
fi

if ! check_cmd "$TMPDIR/wrong_cmd.sh" 2>/dev/null; then
    echo "PASS: Wrong cmd.sh with relative paths correctly fails validation"
else
    echo "FAIL: Wrong cmd.sh should fail validation"
    rm -rf "$TMPDIR"
    exit 1
fi

rm -rf "$TMPDIR"

echo ""
echo "=== ALL SMOKE TESTS PASSED ==="
