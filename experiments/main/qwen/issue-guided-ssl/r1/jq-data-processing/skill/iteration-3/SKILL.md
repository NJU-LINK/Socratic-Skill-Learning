---
name: jq-data-processing
description: >
  Reusable skill for JSON data-processing pipelines using jq. Covers the
  normalize-then-filter-then-shape-then-sort architecture, general N-key
  mixed-direction multi-key sorting via group_by sandwich, ISO 8601 date
  extraction, string normalization (trim, lowercase, domain extraction),
  numeric coercion, boolean derivation, blocked-domain exclusion with dual
  normalization, role deduplication and aggregation, null/blank fallback
  handling, cross-record aggregation via group_by, deeper field access with
  optional chaining, and jq_args.yaml generation for reproducible command
  reconstruction.
---

# jq Data-Processing Skill

## 1. Pipeline Architecture

Every task in this family follows a **normalize → filter → shape → sort** pipeline.
The critical invariant is: **compute all normalized intermediates before using them
in any predicate or output field**.

```
[.[] |
  # Step 1: COMPUTE normalized intermediates (bind with `as`)
  (<normalize expression 1>) as $norm1 |
  (<normalize expression 2>) as $norm2 |
  ...
  # Step 2: FILTER using normalized values
  select(<predicate using $norm1, $norm2, ...>) |
  select(<predicate 2>) |
  ...
  # Step 3: SHAPE the output record
  {
    output_field1: <derived from . and $norm*>,
    output_field2: ...,
  }
] |
# Step 4: SORT the final array
<sort expression>
```

### Why this order matters
- Normalizing first avoids repeating expensive transformations in multiple predicates
- Filtering before shaping avoids computing output fields for records that will be discarded
- Sorting last operates on the final shaped records

## 2. String Normalization Patterns

### Trim whitespace
```jq
gsub("^\\s+|\\s+$"; "")
```
Works for any string value. In jq 1.6, `gsub` uses Oniguruma regex.

### Lowercase
```jq
ascii_downcase
```

### Combined trim + lowercase (for role normalization, domain normalization)
```jq
gsub("^\\s+|\\s+$"; "") | ascii_downcase
```

### Email domain extraction
```jq
.email | split("@")[1] | ascii_downcase
```
Extracts the part after `@` and normalizes to lowercase.

### Phone / optional field fallback
```jq
(.phone // "" | gsub("^\\s+|\\s+$"; "")) as $p |
if $p == "" then "unknown" else $p end
```
Pattern: null-coalesce to empty string, trim, then check if blank.
Replace `"unknown"` with whatever default the task specifies.

### Numeric coercion
```jq
"42" | tonumber          # → 42
"3.14" | tonumber         # → 3.14
```
Use `tonumber` to convert string representations to numbers. Guard against
invalid input with `try ... catch` or type checks.

### Boolean derivation
```jq
# Derive boolean from condition
[.roles[] | ascii_downcase] | any(. == "admin")  # → true/false

# Convert boolean to 0/1
if .is_active then 1 else 0 end

# Null-safe boolean
(.optional_field != null)  # → true if field exists and is not null
```

## 3. ISO 8601 Date Extraction

jq 1.6 has no datetime parser. For standard ISO 8601 timestamps
(`"2026-03-16T05:01:40.829540Z"`), extract the date portion with string slicing:

```jq
.last_login[0:10]
```

This always yields `"YYYY-MM-DD"` because ISO 8601 fixes the date in the first
10 characters. For null/missing safety:

```jq
(.last_login // "")[0:10] | if . == "" then null else . end
```

## 4. Collection Operations

### Deduplicate and sort an array
```jq
[.roles[] | gsub("^\\s+|\\s+$"; "") | ascii_downcase] | unique
```
`unique` in jq both deduplicates AND sorts ascending. This is the standard
pattern for "normalized sorted role list."

### Check if any element matches a condition
```jq
any($norm_roles[]; . == "admin" or . == "owner")
```

### Check that no element matches (exclusion)
```jq
$norm_blocked | all(. != $email_domain)
```
Equivalently: `([$norm_blocked[] | select(. == $email_domain)] | length) == 0`

### Count elements
```jq
$norm_roles | length
```

### First element or null
```jq
if ($norm_roles | length) > 0 then $norm_roles[0] else null end
```

## 4b. Cross-Record Aggregation

When the task requires summarizing data **across** records (not just per-record
transformation), use `group_by` to cluster records, then aggregate within each
group.

### Group and count
```jq
group_by(.domain) |
map({
  domain: .[0].domain,
  count: length,
  names: [.[].username] | unique | sort
})
```

### Group and sum/aggregate a field
```jq
group_by(.category) |
map({
  category: .[0].category,
  total: (map(.amount) | add),
  max_amount: ([.[].amount] | max),
  entries: length
})
```

### Flatten arrays across records
```jq
# Collect all roles from all users into one deduplicated list
[.[].roles[]] | unique

# Collect all values of a specific field
[.[].email_domain] | unique | sort
```

### Combine per-record transformation with cross-record aggregation
```jq
# First transform each record, then aggregate
def normalize: ... ;  # per-record transformation
[.[] | normalize] |   # array of transformed records
group_by(.some_field) |
map({key: .[0].some_field, items: .})
```

### Max/min with associated records
```jq
group_by(.domain) |
map(
  . as $group |
  {
    domain: .[0].domain,
    max_score: ([$group[].score] | max),
    top_users: [$group[] | select(.score == ([$group[].score] | max)) | .name] | unique
  }
)
```

## 5. Mixed-Direction Multi-Key Sorting

jq's `sort_by` only sorts ascending. For mixed ascending/descending across
multiple keys, use the **group_by sandwich** pattern.

### 2-Key Case (primary ASC, secondary DESC)

```jq
sort_by(.secondary) | reverse |        # Step 1: descending on secondary key
group_by(.primary) |                    # Step 2: group by primary (preserves inner order)
[.[] | .[]]                            # Step 3: flatten (group_by already sorts groups ascending)
```

**Why this works:**
1. `sort_by(.secondary) | reverse` — establishes descending order on the secondary key
2. `group_by(.primary)` — groups records by primary key; `group_by` preserves the relative input order within each group and sorts groups ascending by the grouping key
3. Flatten back to a single array

### General N-Key Algorithm

For **any combination** of ascending/descending across N keys, process from
**least significant to most significant**:

**Step 1 (least significant key):**
- ASC: `sort_by(.key)`
- DESC: `sort_by(.key) | reverse`

**Step 2+ (each more significant key):**
- ASC: `group_by(.key) | [.[] | .[]]`
- DESC: `group_by(.key) | reverse | [.[] | .[]]`

**Why this works:** `group_by(.key)` groups elements and sorts groups ascending by key, while preserving the input order within each group. For DESC, `reverse` reverses the order of groups (making the key descending) without changing each group's internal order. Since jq's sort is stable, prior key orderings are preserved within ties.

**Example: 3 keys — domain ASC, name DESC, score ASC:**
```jq
# Step 1: score ASC (least significant)
sort_by(.score) |
# Step 2: name DESC
group_by(.name) | reverse | [.[] | .[]] |
# Step 3: domain ASC (most significant)
group_by(.domain) | [.[] | .[]]
```

**Example: 3 keys — domain ASC, name DESC, score DESC:**
```jq
# Step 1: score DESC
sort_by(.score) | group_by(.score) | reverse | [.[] | .[]] |
# Step 2: name DESC
group_by(.name) | reverse | [.[] | .[]] |
# Step 3: domain ASC
group_by(.domain) | [.[] | .[]]
```

**Shortcut for uniform direction:**
- All ASC: `sort_by(.k1, .k2, .k3)`
- All DESC: `sort_by(.k1, .k2, .k3) | reverse`

## 6. Output Shaping

### Field renaming
```jq
{ user_id: .id, username: .username }
```

### Computed fields
```jq
{ contact: "\(.username) <\(.email)>" }
```

### Nested output objects
```jq
{
  account_summary: {
    role_count: ($norm_roles | length),
    primary_role: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end),
    roles: $norm_roles
  }
}
```

### Deeper field access and optional nested objects
```jq
# Access nested fields safely
.address.city                    # → null if .address is missing
.address.city // "unknown"       # → fallback if missing or null

# Optional chaining with try-catch
try .deeply.nested.field catch null

# Access array elements safely
.tags[0] // "none"              # → first tag or "none" if empty/missing

# Conditional field inclusion
{ name: .name } + (if .email then {email: .email} else {} end)

# Combining multiple source fields into one output field
{ full_name: "\(.first_name) \(.last_name)" }
{ address_line: "\(.street // ""), \(.city // ""), \(.zip // "")" }
```

## 7. jq_args.yaml Generation

The task requires saving the jq filter and arguments in YAML format for
reproducible reconstruction. The YAML must have exactly these keys:

```yaml
filter: "<jq filter expression as a single string>"
args:
  - "--indent 2"
```

Each item in the `args` list is a **single string** containing one complete
jq argument. When a flag takes a value, combine them into one string with a
space separator (e.g., `"--indent 2"`). Flags without values are just the flag
string (e.g., `"--raw-output"`). **Every item must start with `-`**.

The reconstruction command is:
```bash
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/users.json > /app/verified_admin_contacts.json
```

When the shell evaluates `$(yq -r '.args[]' ...)`, the unquoted `$(...)` causes
word-splitting, so `"--indent 2"` becomes two separate shell arguments `--indent`
and `2` — jq receives them correctly.

**Important:** Use Python's `yaml.dump()` to generate the YAML file to ensure
correct escaping of special characters (backslashes, quotes) in the filter
string. Manual YAML construction is error-prone due to multi-layer escaping
(YAML → yq output → shell double-quote interpretation → jq parsing).

**Self-validation step** (run after generating jq_args.yaml):
```python
import yaml
config = yaml.safe_load(open("/app/jq_args.yaml"))
assert all(arg.startswith("-") for arg in config["args"]), "Every args item must start with -"
```

## 8. cmd.sh Generation

Save the exact jq command with output redirection:
```bash
jq --indent 2 '<filter>' /app/users.json > /app/verified_admin_contacts.json
```

## 9. Common Pitfalls

1. **Forgetting to normalize before comparing**: Role strings like `" Admin "` and `"admin"` must be trimmed and lowercased before checking for privileged roles.

2. **Case-sensitive domain comparison**: Email domains and blocked domains must both be lowercased before comparison. `"PORTAL.IO"` and `"portal.io"` are the same domain.

3. **Not deduplicating roles before counting**: `"admin"` appearing twice should count as 1 unique role, not 2.

4. **Sorting in wrong direction**: Always verify which keys are ascending vs descending. Use the group_by sandwich for mixed directions.

5. **Null phone handling**: `null` phone values and blank/whitespace-only strings should both map to the default (e.g., `"unknown"`).

6. **Blocked domain self-exclusion**: A user whose email domain matches their own blocked-domain list should be excluded. Both sides must be normalized before comparison.

7. **jq_args.yaml args format**: Each item in the `args` list must be a single string starting with `-`. Combine flag and value into one string (e.g., `"--indent 2"` not `["--indent", "2"]`). The shell's word-splitting on `$(yq -r '.args[]' ...)` will separate them correctly when jq receives them.

## 10. Verification Checklist

After producing output, verify:
- [ ] Correct number of records (spot-check exclusions)
- [ ] Users with blocked email domains are excluded
- [ ] Users without privileged roles are excluded
- [ ] Inactive/pending users are excluded
- [ ] Sort order: primary key ascending, secondary key descending
- [ ] Phone field: trimmed, nulls/blanks → default
- [ ] Date field: YYYY-MM-DD format
- [ ] Roles: normalized, deduplicated, sorted ascending
- [ ] role_count matches roles array length
- [ ] primary_role is first element of roles (or null)
- [ ] Reconstruct command from jq_args.yaml produces identical output
- [ ] jq_args.yaml: every args item starts with `-` (combined flag+value strings)
