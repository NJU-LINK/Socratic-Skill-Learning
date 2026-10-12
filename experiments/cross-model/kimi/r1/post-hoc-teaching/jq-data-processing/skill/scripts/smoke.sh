#!/bin/bash
# Smoke tests for jq-data-processing skill snippets
# Run with: bash smoke.sh

set -euo pipefail

cd "$(dirname "$0")"

echo "=== jq Smoke Tests ==="
echo "jq version: $(jq --version)"
echo ""

pass=0
fail=0

run_test() {
    local name="$1"
    local filter_file="$2"
    local expected="$3"
    local result
    
    if result=$(jq -cnf "$filter_file" 2>&1); then
        if [[ "$result" == "$expected" ]]; then
            echo "PASS: $name"
            ((pass++)) || true
        else
            echo "FAIL: $name"
            echo "  Expected: $expected"
            echo "  Got: $result"
            ((fail++)) || true
        fi
    else
        echo "ERROR: $name"
        echo "  $result"
        ((fail++)) || true
    fi
}

# Create test filters
cat > /tmp/test_computed_key.jq << 'EOF'
"dept" as $k | {($k): 42}
EOF

cat > /tmp/test_computed_key_interp.jq << 'EOF'
"count" as $prefix | {("\($prefix)_total"): 5}
EOF

cat > /tmp/test_limit.jq << 'EOF'
[limit(2; [10,20,30][] | select(. > 15))]
EOF

cat > /tmp/test_first.jq << 'EOF'
[{type:"admin",id:1},{type:"user",id:2}] | first(.[] | select(.type == "admin"))
EOF

cat > /tmp/test_match_global.jq << 'EOF'
"abc 123 def 456" | [match("\\d+"; "g")] | map(.string)
EOF

cat > /tmp/test_match_first.jq << 'EOF'
"abc 123 def 456" | match("\\d+") | .string
EOF

cat > /tmp/test_capture.jq << 'EOF'
"123-4567" | capture("(?<area>\\d{3})-(?<num>\\d{4})")
EOF

cat > /tmp/test_in_operator.jq << 'EOF'
"admin" | IN("admin", "owner", "user")
EOF

cat > /tmp/test_any.jq << 'EOF'
["viewer", "admin", "user"] | any(.[]; . == "admin")
EOF

cat > /tmp/test_all.jq << 'EOF'
[10, 20, 30] | all(.[]; . > 5)
EOF

cat > /tmp/test_index.jq << 'EOF'
["a","b","c"] | index("a")
EOF

cat > /tmp/test_select_index.jq << 'EOF'
{tags:["admin","user"]} | select(.tags | index("admin")) | .tags[0]
EOF

cat > /tmp/test_tonumber_valid.jq << 'EOF'
"42" | tonumber? // 0
EOF

cat > /tmp/test_tonumber_invalid.jq << 'EOF'
"not_a_number" | tonumber? // 0
EOF

cat > /tmp/test_stable_sort.jq << 'EOF'
[{a:1,b:"z"},{a:1,b:"a"},{a:2,b:"m"}] | sort_by(.b) | reverse | sort_by(.a) | .[0].b
EOF

# Run tests
run_test "Computed key with variable" "/tmp/test_computed_key.jq" '{"dept":42}'
run_test "Computed key with interpolation" "/tmp/test_computed_key_interp.jq" '{"count_total":5}'
run_test "limit() with generator" "/tmp/test_limit.jq" '[20,30]'
run_test "first() with generator" "/tmp/test_first.jq" '{"type":"admin","id":1}'
run_test "match() global" "/tmp/test_match_global.jq" '["123","456"]'
run_test "match() first only" "/tmp/test_match_first.jq" '"123"'
run_test "capture() with groups" "/tmp/test_capture.jq" '{"area":"123","num":"4567"}'
run_test "IN operator" "/tmp/test_in_operator.jq" 'true'
run_test "any() with generator" "/tmp/test_any.jq" 'true'
run_test "all() with generator" "/tmp/test_all.jq" 'true'
run_test "index() returns 0" "/tmp/test_index.jq" '0'
run_test "select with index(0)" "/tmp/test_select_index.jq" '"admin"'
run_test "tonumber? valid" "/tmp/test_tonumber_valid.jq" '42'
run_test "tonumber? invalid" "/tmp/test_tonumber_invalid.jq" '0'
run_test "Stable sort" "/tmp/test_stable_sort.jq" '"z"'

echo ""
echo "=== Results: $pass passed, $fail failed ==="

# Cleanup
rm -f /tmp/test_*.jq

exit $((fail > 0 ? 1 : 0))
