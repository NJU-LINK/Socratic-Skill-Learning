---
name: jq-data-processing
description: Transform JSON data using jq with filtering, normalization, reshaping, and multi-key sorting
---

# jq Data Processing Skill

Transform JSON records using jq with complex filtering, field normalization, structural reshaping, and multi-key sorting.

## Core Pattern: Normalize → Select → Shape → Collect → Sort

The standard pipeline for complex data transformation tasks:

1. **Normalize** - Bind cleaned values using `as $variable`
2. **Select** - Apply filters using the normalized values
3. **Shape** - Build output records with transformed fields
4. **Collect** - Wrap stream in `[...]` to create an array
5. **Sort** - Apply multi-key sorting with direction control

## Critical: The `.`-Rebinding Rule

**Every `|` rebinds `.`**. When you pipe into a filter that changes context (like `map()`, `select()`, or array operations), the outer `.` is lost.

**Solution**: Capture outer values with `as $variable` before piping:

```jq
# WRONG: .email_domain refers to the array, not the record
select(.blocked_domains | index(.email_domain))

# RIGHT: capture before the pipe
.email_domain as $domain | select(.blocked_domains | index($domain))
```

## Scalar Normalization Chain

Define a reusable normalization function:

```jq
def norm: gsub("^\\s+|\\s+$"; "") | ascii_downcase;
```

**Phone normalization** (handles null, missing, numeric, whitespace):
```jq
((.phone // "") | tostring | gsub("^\\s+|\\s+$"; "")) as $phone_trimmed
| if $phone_trimmed == "" then "unknown" else $phone_trimmed end
```

**Date extraction** (ISO 8601 to YYYY-MM-DD):
```jq
.last_login | .[0:10]  # Simple slice, null-safe
```

**Email domain extraction**:
```jq
.email | split("@") | last | ascii_downcase
```

**Role array normalization** (trim, lowercase, deduplicate, sort):
```jq
.roles | map(norm) | unique  # unique already sorts ascending
```

## Selection Patterns

**Multi-condition AND** (chain selects):
```jq
select(.status == "active")
| select($roles | any(. == "admin" or . == "owner"))
| select($blocked | index($domain) | not)
```

**Membership test** (value in array):
```jq
$blocked | index($domain) | not   # true if $domain NOT in $blocked
```

**Has privileged role** (any element matches):
```jq
$roles | map(. == "admin" or . == "owner") | any
```

## Multi-Key Sorting with Mixed Directions

For "key1 ascending, key2 descending":

```jq
group_by(.key1)           # Groups are sorted by key1 ascending
| map(sort_by(.key2) | reverse)  # Within each group, sort key2 desc
| (add // [])             # Flatten groups back to array
```

**Why this works**: `group_by` returns groups in ascending order of the grouping key. Within each group, we sort by the secondary key and reverse for descending. `add` concatenates the groups; `// []` handles empty input.

**Alternative** (if stable sort is guaranteed):
```jq
sort_by(.key2) | reverse | sort_by(.key1)  # Risky - relies on stability
```

## Collection Operations

**Count unique items**: `($roles | length)`

**First item or null**: `$roles[0]`  # Returns null for empty array

**String interpolation**: `"\(.username) <\(.email)>"`

**Conditional value**: `if $phone_trimmed == "" then "unknown" else $phone_trimmed end`

### Grouped Aggregation

Summarize records after grouping:

```jq
group_by(.email_domain)
| map({
    domain: .[0].email_domain,       # group key from any member
    count: length,                     # aggregate over the group
    admins: map(select(.account_summary.roles | index("admin"))) | length
  })
```

**Pattern**: `group_by(key) | map({key: .[0].key, ...aggregates...})`

### Combined Transform + Cross-Record Summary

Emit records with a wrapping summary object:

```jq
[.[] | ...selects... | {...record...}] as $records
| {
    total: ($records | length),
    by_domain: ($records | group_by(.email_domain)
                  | map({domain: .[0].email_domain, count: length})),
    records: $records
  }
```

**Pattern**: Bind the transformed array with `as`, then build an object carrying both aggregates and the records.

### Flatten, Rebuild, and Custom Folds

**Collapse arrays into deduplicated list**:
```jq
[.[] | .tags[]] | unique    # All unique tags across all records
```

**Custom aggregation with reduce** (when built-ins don't fit):
```jq
reduce .[] as $x (0; . + ($x.amount | tonumber? // 0))
```

## Verification: Prove Each Predicate Bites

For every filter condition, verify it actually excludes records:

```jq
# Count what each predicate eliminates
[ .[]
  | (.roles | map(norm) | unique) as $r
  | select(.status == "active")
  | if ($r | any(. == "admin" or . == "owner"))
    then "has_privileged"
    else "no_privileged" end
] | group_by(.) | map({(.[0]): length}) | add
```

A filter that removes 0 records when the data was built to exercise it is a bug hiding behind valid JSON.

## Output Structure Patterns

**Flat object reshaping**:
```jq
{
  user_id: .id,                    # Rename field
  username: .username,              # Keep as-is
  email_domain: $domain,            # Use normalized binding
  contact: "\(.username) <\(.email)>",  # Computed string
  phone: $phone_clean,              # Normalized scalar
  account_summary: {                # Nested object
    role_count: ($roles | length),
    primary_role: $roles[0],
    roles: $roles
  }
}
```

## Deliverable Files

### cmd.sh
Write the exact executed command. Use quoted heredoc `<<'EOF'` to preserve `$variables`:
```bash
cat > /app/cmd.sh <<'EOF'
jq --indent 2 '...filter...' /app/input.json > /app/output.json
EOF
```

### jq_args.yaml
Use block scalar `|-` for the filter to preserve backslashes. **Critical**: each `args` item must be one complete argument starting with `-`:
```yaml
filter: |-
  def norm: gsub("^\\s+|\\s+$"; "") | ascii_downcase;
  [.[] | ... ]
args:
  - "--indent 2"
```
**Wrong** (value `"2"` doesn't start with `-`, fails contract validation):
```yaml
args:
  - "--indent"
  - "2"
```

## Reconstruction Verification

**Behavioral check** (produces equivalent output):
```bash
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" \
  /app/input.json > /tmp/recon.json \
  && diff /tmp/recon.json /app/output.json && echo "RECON-OK"
```

**Contract check** (proves artifact complies with schema — graders check both):
```bash
# Every arg must start with "-"
yq -r '.args[] | startswith("-")' /app/jq_args.yaml   # must print only "true"

# Keys must be exactly: filter,args (order may vary)
yq -r 'keys | sort | join(",")' /app/jq_args.yaml     # must be: "args,filter"
```

## Complete Example Template

```jq
def norm: gsub("^\\s+|\\s+$"; "") | ascii_downcase;

[.[] |
  # Normalize and bind
  (.roles | map(norm) | unique) as $roles |
  (.email | split("@") | last | ascii_downcase) as $domain |
  (.blocked_domains | map(norm)) as $blocked |
  ((.phone // "") | tostring | gsub("^\\s+|\\s+$"; "")) as $phone_trimmed |
  
  # Select
  select(.status == "active") |
  select($roles | map(. == "admin" or . == "owner") | any) |
  select($blocked | index($domain) | not) |
  
  # Shape output
  {
    user_id: .id,
    username: .username,
    email: .email,
    email_domain: $domain,
    contact: "\(.username) <\(.email)>",
    phone: (if $phone_trimmed == "" then "unknown" else $phone_trimmed end),
    last_login: (.last_login | .[0:10]),
    account_summary: {
      role_count: ($roles | length),
      primary_role: $roles[0],
      roles: $roles
    }
  }
] |
  # Sort: email_domain asc, username desc
group_by(.email_domain) | map(sort_by(.username) | reverse) | (add // [])
```

## Optional and Fallback Patterns

**Safe nested access**: Use `?` to suppress "Cannot index" errors when intermediate values might be non-objects:
```jq
.a.b.c? // "default"    # Returns default if any of a,b,c missing OR wrong type
```

**Coercion with fallback**:
```jq
(.value | tonumber? // 0)   # null or unparseable → 0
```

**Warning**: `//` swallows `false` and `null`, not just `null`:
```jq
jq -n '[false // true, null // 7, 0 // 5, "" // "x"]'
# → [true, 7, 0, ""]   # false/null fall back; 0/""/[] are preserved

# WRONG: converts actual false into true
.flag // true

# RIGHT: only null/missing falls back to default
if .flag == null then true else .flag end
```

## Common Pitfalls

1. **Unquoted heredoc**: `<<EOF` expands `$variables`; use `<<'EOF'`
2. **Forgetting `.` rebinding**: Capture outer values with `as $x` before pipes
3. **Assuming stable sort**: Use `group_by` + `map(reverse)` for mixed directions
4. **Not verifying filters**: Check that each `select` actually excludes records
5. **YAML mangling**: Use `|-` block scalar for filters containing backslashes
6. **`//` swallowing false**: `//` treats null and false as missing (but preserves 0, "", []). Use explicit `if .x == null then ... else .x end` when a real `false` must survive
