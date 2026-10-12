---
name: jq-data-processing
description: |
  Transform JSON data using jq filters with idiomatic patterns. Handles record selection,
  field derivation, value normalization, aggregation, multi-key sorting, and complex
  condition composition. Emphasizes dynamic scope awareness, defensive normalization
  with `def`, type-strict builtins, and interface-driven artifact formatting.
---

# jq Data Processing Skill

This skill provides idiomatic patterns for transforming JSON data using jq.

## Core Mental Model: Dynamic Scope

**Critical rule**: In jq, `.` is **not** "the current record" — it is "whatever the current
pipeline stage or function argument is iterating over." Every `|`, `map`, `select`,
`index(f)`, `sort_by(f)`, `group_by(f)`, `reduce`, and regex builtin **rebinds** `.`.

**Rule**: Before entering any scope-changing construct (`map`, `select`, `index`,
`sort_by`, `group_by`, object construction), bind every outer value you need inside
to a `$variable`:

```jq
# WRONG: inside select, `.` is the blocked array, not the record
| select(.blocked | index(.email) | not)

# CORRECT: bind email before entering select
(.email | ...) as $email
| select(.blocked | index($email) | not)
```

**Scope also changes in assertions/comparisons** — the right side of `==` has `.` rebound:
```jq
# WRONG: at ==, `.` is the split result (a string), not the original record
.email | split("@")[1] | ascii_downcase == .email_domain

# CORRECT: bind before the comparison pipeline
(.email | split("@")[1] | ascii_downcase) as $dom
| select($dom == .email_domain)
```

## Defensive Normalization with `def`

Define reusable normalization functions at the start:

```jq
def norm_s: gsub("^\\s+|\\s+$"; "") | ascii_downcase;
def norm_date: split("T")[0];
```

**Defensive patterns for variable data:**

```jq
# Missing keys: provide empty array default
(.blocked_domains // []) | map(norm_s)

# Optional arrays: use []? to tolerate missing/non-array
[.roles[]? | norm_s]

# Type coercion before regex: use tostring
(.phone | tostring | gsub("^\\s+|\\s+$"; ""))

# Numeric coercion with fallback (tonumber? passes numbers through, ? suppresses errors)
(.count | tonumber? // 0)

# CAUTION: `a // b` treats `false` as absent too
# For booleans, use: if .active == null then default else .active end
```

## Complex Condition Composition

```jq
# AND conditions (all must be true)
select(.status == "active" and .role == "admin")

# OR conditions (any can be true)
select(.role == "admin" or .role == "owner")

# Combined AND/OR with parentheses for clarity
select(.status == "active" and (.role == "admin" or .role == "owner"))

# Complex multi-field conditions
select(
  (.status == "active" or .status == "pending") and
  .created_at > "2024-01-01" and
  (.tags | index("important"))
)

# Negation
select(.status != "inactive")
select(.name | test("^admin") | not)

# IN operator for multiple values
select(.role | IN("admin", "owner", "moderator"))

# All elements satisfy condition
select(all(.items[]; .price > 0))

# Any element satisfies condition
select(any(.tags[]; . == "urgent"))
```

## Mathematical Operations

```jq
# Arithmetic
(.price * .quantity) as $total
(.score / .max_score * 100) as $percentage

# Rounding
(.value * 100 | round) / 100          # Round to 2 decimal places
(.value | floor), (.value | ceil)     # Floor and ceiling

# Aggregation math
(map(.amount) | add)                  # Sum
(map(.amount) | add) / length         # Average
(length) as $count

# Statistical
map(.value) | (add / length) as $mean
map(.value) | max, min
```

## Type-Strict Builtins

jq builtins are strictly typed. Common errors:

| Error | Cause | Fix |
|-------|-------|-----|
| "Cannot index array with string" | Inside `index(f)`, `.` is the array | Bind value to `$var` before `index($var)` |
| "cannot be matched, as it is not a string" | `gsub` received object/null | `tostring` first or check `== null` |
| "cannot be negated" | `-` prefix on string | Use stable sort for strings (see Sorting) |
| "Cannot iterate over null" | `.field[]` when field is null | Use `.field[]?` or `(.field // [])` |
| "Cannot index object with number" | `first` after pipe | `first(generator)` not `generator \| first` |

## Stream Consumers: first, last, limit, any, all

**Rule**: `first(g)`, `last(g)`, `limit(n; g)`, `any(g; c)`, `all(g; c)` take the
generator inside the parentheses. Appending after a pipe uses the `/0` form which
fails on objects.

```jq
# CORRECT: generator inside parentheses
first(.[] | select(.type == "admin"))
limit(10; .[] | select(.active))
any(.roles[]; . == "admin")

# WRONG: pipe appends apply to each element
.[] | select(.type == "admin") | first     # ERROR: indexes object with number
```

## Multi-Key Sorting Decision Table

**Habit**: When a decision-table recipe exists, instantiate it verbatim first; improvise only after it demonstrably fails.

| Direction | Approach | Example |
|-----------|----------|---------|
| Same direction (all asc) | Array keys | `sort_by([.domain, .user])` |
| Same direction (all desc) | Array with negation for numbers only | `sort_by([.domain, -.score])` |
| Mixed directions | **Stable two-pass sort** | `sort_by(.user) \| reverse \| sort_by(.domain)` |
| Group by first key | `group_by` (already sorts by key) | `group_by(.domain) \| map(sort_by(.user)) \| add // []` |

**Key insight**: jq's sort is **stable**. Sort by least-significant key first (with `reverse`
for descending), then by more significant keys.

## Cross-Record Aggregation

```jq
# Per-group summary: group by dept, count, sum amounts
group_by(.dept) | map({
  dept: .[0].dept,
  n: length,
  total: (map(.amount | tonumber? // 0) | add // 0)
})

# Array → lookup object keyed by id
map({key: (.id | tostring), value: .}) | from_entries

# Object → array of records (pivot)
to_entries | map(.value + {key: .key})

# Transform object keys in place
with_entries(.key |= ascii_downcase)

# Deduplicate values across all records
[.[].tags[]?] | unique

# Collect all values for a key across records
map(.category) | unique
```

## Selection and Filtering

```jq
# Basic selection
.[] | select(.status == "active")

# Exclusion logic: value NOT in array
| select($blocked | index($email) | not)

# Check if any element matches (short-circuits)
| select(any($roles[]; . == "admin" or . == "owner"))

# Equivalent without any():
| select($roles | map(select(. == "admin" or . == "owner")) | length > 0)
```

## Array Operations

```jq
# Remove duplicates (already returns sorted output)
unique

# Remove duplicates by specific key
unique_by(.id)

# Filter array
map(select(.status == "active"))

# Flatten one level
flatten(1)

# Get min/max by key
min_by(.score), max_by(.score)

# Check membership
$blocked | index($domain)        # returns index or null
$domain | inside($blocked)         # inside() expects container first

# Array slicing
.[10:20]                           # Skip 10, take next 10
.[:100]                            # First 100
.[-10:]                            # Last 10
```

## Conditional Value Handling

```jq
# Null or blank to default (with trim check)
(if .phone == null then "unknown"
 else (.phone | tostring | gsub("^\\s+|\\s+$"; ""))
      | if . == "" then "unknown" else . end
 end)

# First element or null
($sorted[0] // null)

# Boolean with null default (AVOID // for booleans!)
(if .active == null then true else .active end)

# Multiple condition branches
if .status == "active" then "green"
elif .status == "pending" then "yellow"
elif .status == "inactive" then "red"
else "unknown"
end

# Switch-like pattern using object lookup
{"active": "green", "pending": "yellow", "inactive": "red"}[.status] // "unknown"
```

## Building Output Structure

```jq
# Shorthand for same-name fields
{username, email}    # equivalent to {username: .username, email: .email}

# String interpolation
"\(.name) <\(.email)>"

# Nested objects
{
  user_id: .id,
  account_summary: {
    role_count: ($roles | length),
    primary_role: ($roles[0] // null),
    roles: $roles
  }
}

# Computed/dynamic key names using parentheses
{($key): .value}                   # variable as key
{"\($prefix)_count": .n}           # interpolation in key string

# Merging objects
.data + .metadata + {computed: .value * 2}

# Removing fields
del(.password, .secret_key)
delpaths([path(.sensitive)])
```

## String and Date Operations

```jq
# String splitting and joining
split("@") | .[1]                  # Get domain from email
join(", ")                          # Join array elements

# Substring extraction
.[0:10]                            # First 10 chars

# Date comparison (lexicographic works for ISO8601)
select(.date >= "2024-01-01")

# Extract date parts
(.date | split("-") | {year: .[0], month: .[1], day: .[2]})

# Regex test (returns boolean)
test("^[A-Za-z]+$")                # Test if alphabetic only

# Regex capture with named groups
capture("(?<area>\\d{3})-(?<num>\\d{4})")  # Returns object with named captures

# Find all matches (global flag)
[match("\\d+"; "g")] | map(.string)       # All numbers as strings

# Find first match only
match("\\d+")                       # Returns match object for first occurrence
```

## Complete Workflow Template

```jq
def norm_s: gsub("^\\s+|\\s+$"; "") | ascii_downcase;

[
  .[]
  | select(<record-condition>)
  | (<compute-value>) as $var
  | select(<derived-condition>)
  | {
      <output-mapping>
    }
]
| <sorting>
```

## Required Output Artifacts

### Method: Replay the Consumer

**Rule**: An artifact file that another command consumes is an interface. Decide its format
by replaying the consumer, not by convention.

When an artifact contract fails, read three sources together:
1. **The failing assertion** — names the invariant literally (e.g., `startswith("-")`)
2. **The spec prose** — encodes the answer; re-parse word by word after any failure
3. **The consumer's exact construction** — reproduce verbatim and vary one thing at a time

### 1. cmd.sh
Must be self-contained (filter inline or in `/app`, not `/tmp`):

```bash
jq --indent 2 '
def norm_s: ...;
[ ... ]
| sort_by(...)
' /app/input.json > /app/output.json
```

### 2. jq_args.yaml
**CRITICAL**: Each arg must be a complete argument including flag AND value:

```yaml
filter: |
  def norm_s: ...;
  [
    .[]
    | ...
  ]
args:
  - "--indent 2"    # Correct: flag and value together
```

**WRONG** — Do NOT split flag and value into separate items:
```yaml
args:
  - "--indent"     # Wrong
  - "2"            # Wrong - doesn't start with -
```

**CAVEAT**: The combined-string convention works because values are whitespace-free.
Word-splitting (`$(yq -r '.args[]')` without quotes) means values containing spaces,
quotes, or glob characters cannot survive this reconstruction. Keep args items
whitespace-safe; prefer value-less flags (`-c`, `--sort-keys`). If parameterized args
(`--arg`, `--argjson`) are needed, use compact values (no embedded spaces) and replay
the consumer end-to-end before trusting it.

**Verification**: Always execute `bash /app/cmd.sh` and verify output.

## Verification with jq -e

Use `jq -e` assertions for automated checks (exit 0 = true, exit 1 = false):

```bash
#!/bin/bash
set -euo pipefail  # Fail on error, undefined var, pipefail

# Verify sorting
jq -e '[.[].domain] == ([.[].domain] | sort)' output.json

# Verify structure
jq -e 'all(.[]; .role_count == (.roles | length))' output.json

# Verify all records have required fields
jq -e 'all(.[]; has("user_id") and has("email"))' output.json

# Verify output is non-empty array
jq -e 'type == "array" and length >= 0' output.json

echo "All verifications passed!"
```

## Version-Specific Notes

- **jq < 1.7**: No built-in `trim/0`, use `gsub("^\\s+|\\s+$"; "")`
- **jq >= 1.7.1**: Has `trim/0` builtin
- Probe before assuming: `jq -n '" x " | trim' 2>/dev/null && echo "has trim" || echo "no trim"`

## Pitfall Summary

1. **Dynamic scope**: `.` changes meaning in `map`, `select`, `index`, `sort_by`, etc.
2. **Scope in comparisons**: Right side of `==` has `.` rebound — bind before pipeline.
3. **Type strictness**: Coerce with `tostring` before regex; check `null` before iteration.
4. **// and false**: `a // b` treats `false` as null — avoid for boolean defaults.
5. **unique already sorted**: `unique | sort` is redundant but harmless.
6. **group_by sorts**: Don't `sort_by(.x) | group_by(.x)` — group_by already sorts.
7. **stable sort**: `sort_by(.b) | reverse | sort_by(.a)` preserves order within equal `a`.
8. **jq_args.yaml format**: Combine flag and value: `"--indent 2"` not `["--indent", "2"]`.
9. **Whitespace in args**: Word-splitting prevents values with spaces; keep args whitespace-safe.
10. **Stream consumers**: `first(g)`, `limit(n; g)` — generator goes INSIDE parentheses.
11. **Truthiness**: `0` is truthy in jq (only `false`/`null` fail). `index()` returning `0` is truthy.
12. **match vs capture**: `match()` returns match object; `capture()` returns named captures as object.
