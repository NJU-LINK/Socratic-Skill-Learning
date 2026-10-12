---
name: jq-data-processing
description: >
  Transform JSON input files into structured JSON reports using jq. Covers
  record filtering with multi-condition predicates, field renaming and
  derivation, value normalization (string trimming, case conversion, date
  extraction, null fallbacks), collection operations (deduplication, sorting,
  counting), and mixed ascending/descending sort orders. Produces the jq
  filter, a shell command file, and a YAML args manifest.
---

# jq Data Processing

## When to Apply

Use this skill when the task asks you to:
- Read a JSON input file and produce a transformed JSON output file
- Use `jq` as the transformation tool
- Save artifacts: a jq filter, a shell command (`cmd.sh`), and a YAML args file (`jq_args.yaml`)

## Execution Workflow

### 1. Inspect the Input Data

Before writing any jq, examine the input to understand its shape:

```bash
# Type and size
jq 'type' /app/input.json
jq 'length' /app/input.json

# First record structure
jq '.[0]' /app/input.json

# Field inventory and value variety
jq '[.[] | keys] | .[0]' /app/input.json
jq '[.[] | .status] | unique' /app/input.json
jq '[.[] | .roles // [] | .[]] | unique' /app/input.json
```

Identify:
- Whether input is an array of objects or a single object
- All field names and their types (string, number, array, object, null)
- Value variations that affect filtering (e.g., mixed case, whitespace)
- Fields that may be null, missing, or blank

### 2. Decompose the Task into Pipeline Stages

Every jq transformation in this family follows this general pipeline:

```
INPUT
  | [stage 1: iterate elements]
  | [stage 2: filter records]
  | [stage 3: normalize values on each record]
  | [stage 4: derive new fields / reshape structure]
  | [stage 5: aggregate or collect across fields]
  | [stage 6: wrap in array and sort]
OUTPUT
```

Not all stages are always needed. Read the task to determine which apply.

### 3. Build the jq Filter

#### 3a. Selection and Ordering Logic

**Single-condition filter:**
```jq
.[] | select(.status == "active")
```

**Multi-condition filter (AND):**
```jq
.[] | select(.status == "active" and .age > 18)
```

**Inclusion filter (OR across values):**
```jq
.[] | select(.role | IN("admin"; "owner"; "editor"))
```
Or equivalently with `any`:
```jq
.[] | select([.roles[] | . == "admin" or . == "owner"] | any)
```

**Exclusion filter (NOT):**
```jq
.[] | select(.domain as $d | .blocked[] | . == $d | not)
```

**Comparing against a derived/normalized value:**
When a filter depends on a normalized value (e.g., trimmed, lowercased), normalize first, then filter:
```jq
.[]
| .roles = [.roles[] | gsub("^\\s+|\\s+$"; "") | ascii_downcase]
| select(.roles | any(. == "admin"))
```

**Sort with mixed ascending/descending:**
jq's `sort_by` only does ascending. For mixed orders, use the stable-sort trick:
- Sort by the secondary key in the *opposite* direction first
- Then sort by the primary key in the desired direction

Example — primary ascending by `domain`, secondary descending by `username`:
```jq
| sort_by(.username) | reverse   # username descending
| sort_by(.email_domain)          # domain ascending (stable: preserves username desc within ties)
```

For purely descending: `sort_by(.field) | reverse`
For multiple ascending keys: `sort_by(.field1, .field2)`

#### 3b. Field Derivation and Reshaping

**Rename a field:**
```jq
{new_name: .old_name, ...rest}
```
Or build the object explicitly listing all fields.

**Combine fields into a derived string:**
```jq
contact: "\(.username) <\(.email)>"
```

**Extract from nested objects:**
```jq
.address.city          # direct access
.address?.city // "N/A"  # safe access with fallback
```

**Emit nested output objects:**
```jq
account_summary: {
  role_count: (.roles | length),
  primary_role: (.roles[0] // null),
  roles: .roles
}
```

**Flatten or rebuild arrays:**
```jq
[.items[] | .tags[]]           # flatten nested arrays
[.items[] | {name, category}]  # rebuild array of new objects
```

#### 3c. Value Normalization

**Trim whitespace:**
```jq
.phone | gsub("^\\s+|\\s+$"; "")
```

**Lowercase:**
```jq
.email | ascii_downcase
```

**Extract date from ISO 8601 timestamp:**
```jq
.last_login | split("T")[0]           # "2026-03-16T05:01:40Z" -> "2026-03-16"
# Or with capture:
.last_login | capture("(?<d>[0-9]{4}-[0-9]{2}-[0-9]{2})") | .d
```

**Null/blank fallback:**
```jq
# When value may be null or blank string:
if .phone == null or (.phone | gsub("^\\s+|\\s+$"; "")) == ""
then "unknown"
else (.phone | gsub("^\\s+|\\s+$"; ""))
end

# Shorter form for non-blank nulls:
.phone // "unknown"

# For numeric coercion with fallback:
(.count | tonumber? // 0)
```

**Boolean derivation:**
```jq
is_active: (.status == "active")
has_roles: ((.roles | length) > 0)
```

**Normalize an array of strings (trim, lowercase, deduplicate, sort):**
```jq
.roles = [.roles[] | gsub("^\\s+|\\s+$"; "") | ascii_downcase] | .roles = (.roles | unique)
```
Note: `unique` in jq already sorts the result.

#### 3d. Aggregation and Collection Operations

**Count unique values:**
```jq
role_count: (.roles | unique | length)
```

**First/last from sorted array:**
```jq
primary_role: (if (.roles | length) == 0 then null else .roles[0] end)
```

**Deduplicate:**
```jq
.roles | unique
```

**Group records:**
```jq
group_by(.department) | map({
  dept: .[0].department,
  members: [.[] | .name],
  count: length
})
```

**Cross-record aggregation:**
```jq
[.[] | select(.active)] | {
  total: length,
  avg_age: (map(.age) | add / length)
}
```

### 4. Handle Variable Binding for Cross-Field Comparisons

When comparing two fields on the same record after a transformation, use variable binding to avoid losing context:

```jq
. as $rec
| [.blocked_domains[]? | normalize] as $blocked
| select(($blocked | index($rec.email_domain)) == null)
```

This pattern is essential when:
- A computed value must be compared against another computed value
- An intermediate array derivation would shadow the parent object's fields
- The `?` operator is needed to handle potentially missing arrays

### 5. Assemble the Output

**Collect into array:** Wrap the entire pipeline in `[...]` to produce a JSON array:
```jq
[ .[] | select(...) | {...} ] | sort_by(...)
```

**Indentation:** jq defaults to 2-space pretty-print. No special flag needed. If a different indent is required, pass `--indent N` as a jq argument.

### 6. Generate Required Artifacts

#### The jq filter
Write the complete jq expression as the `filter` value in `jq_args.yaml`.

#### `/app/jq_args.yaml`
Format:
```yaml
filter: |
  [your jq expression here, using YAML literal block scalar]
args: []
```

If additional jq CLI arguments are needed (e.g., `--slurp`, `--raw-output`, `--arg name value`), add them as individual strings:
```yaml
args:
  - "--slurp"
  - "--arg"
  - "cutoff"
  - "2026-01-01"
```

**Important:** The YAML `filter` field uses a literal block scalar (`|`). Write the jq filter exactly as you would in a shell single-quoted argument. YAML `|` blocks do not process escape sequences, so `\\s` in the YAML file stays as `\\s` when extracted, and jq's string parser then interprets `\\s` as regex `\s`. This means regex patterns in the YAML look the same as in a normal jq shell command (e.g., `gsub("^\\s+|\\s+$"; "")`).

#### `/app/cmd.sh`
The shell command that reconstructs and runs jq from the YAML:
```bash
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/users.json > /app/verified_admin_contacts.json
```

Adjust input/output filenames to match the task. When `args` is empty, `$(yq -r '.args[]' ...)` expands to nothing, which is correct.

### 7. Self-Verification Checklist

After producing output, verify:

1. **Output is valid JSON:** `jq empty /app/output.json`
2. **Record count is reasonable:** `jq 'length' /app/output.json`
3. **Sort order is correct:**
   ```bash
   # Check primary ascending:
   jq '[.[].sort_field1]' /app/output.json | jq '. == sort'
   # Check secondary descending within groups:
   jq 'group_by(.field1) | map([.[] | .field2] | . == (sort | reverse)) | all' /app/output.json
   ```
4. **No excluded records leaked through:** Spot-check that records failing the filter predicate are absent.
5. **Normalized values are consistent:** Check that strings are lowercase, trimmed, dates are in correct format.
6. **Null fallbacks applied:** `jq '[.[] | .phone] | map(select(. == null))' /app/output.json` should return `[]`.
7. **cmd.sh reproduces output:** `rm /app/output.json && bash /app/cmd.sh && diff ...`
8. **jq_args.yaml reconstructs correctly:** `yq -r '.filter' /app/jq_args.yaml | head -3`

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| `Cannot index array with string` | You lost object context; use `as $var` binding before array operations |
| Regex escapes confused in YAML | Write `\\s` in YAML `\|` block (same as shell jq). YAML `\|` preserves it literally; jq string parser turns `\\s` into regex `\s` |
| `sort_by` can't do descending | Use stable-sort trick: reverse-sort secondary first, then sort primary |
| `null` phone causes `.strip()` error | Check for null *before* string operations: `if .phone == null or ...` |
| `unique` already sorts | Don't add a separate `sort` after `unique` |
| Missing array field crashes `[]` | Use `[]?` (try operator) for optional arrays |
| Shell quoting breaks filter | Use `"$(yq -r '.filter' file)"` with double quotes around the substitution |

## jq Function Quick Reference

| Need | jq Expression |
|------|---------------|
| Trim whitespace | `gsub("^\\s+\|\\s+$"; "")` |
| Lowercase | `ascii_downcase` |
| Uppercase | `ascii_upcase` |
| Split string | `split("T")[0]` |
| Regex match | `test("pattern")` |
| Regex capture | `capture("(?<name>pattern)")` |
| Replace | `gsub("old"; "new")` |
| Array dedup+sort | `unique` |
| Array flatten | `[.[] | .sub[]]` |
| Group records | `group_by(.key)` |
| Null fallback | `// default` |
| Safe access | `.field? // default` |
| String interp | `"\(.a) text \(.b)"` |
| Numeric coercion | `tonumber` or `tonumber? // 0` |
| Array membership | `IN("a";"b";"c")` or `[.[] == "x"] \| any` |
| Array index lookup | `.array \| index(value)` (returns null if absent) |
| Conditional | `if COND then A else B end` |
| Object merge | `obj1 + obj2` or `{a:1} + {b:2}` |
