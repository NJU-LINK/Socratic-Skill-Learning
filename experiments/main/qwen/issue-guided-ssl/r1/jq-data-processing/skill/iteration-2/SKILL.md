---
name: jq-data-processing
description: >
  Reusable skill for JSON data-processing pipelines using jq. Covers the
  normalize-then-filter-then-shape-then-sort architecture, mixed-direction
  multi-key sorting, ISO 8601 date extraction, string normalization (trim,
  lowercase, domain extraction), blocked-domain exclusion with dual
  normalization, role deduplication and aggregation, null/blank fallback
  handling, and jq_args.yaml generation for reproducible command reconstruction.
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

## 5. Mixed-Direction Multi-Key Sorting

jq's `sort_by` only sorts ascending. For mixed ascending/descending across
multiple keys, use the **group_by sandwich** pattern:

```jq
# Example: sort by field_a ASC, then field_b DESC
sort_by(.field_b) | reverse |          # Step 1: descending on secondary key
group_by(.field_a) |                    # Step 2: group by primary key (preserves inner order)
sort_by(.[0].field_a) |                # Step 3: sort groups by primary key ascending
[.[] | .[]]                            # Step 4: flatten
```

**Why this works:**
1. `sort_by(.field_b) | reverse` — establishes descending order on the secondary key
2. `group_by(.field_a)` — groups records by primary key; crucially, `group_by` preserves the relative input order within each group
3. `sort_by(.[0].field_a)` — sorts the groups by the primary key ascending (stable sort)
4. Flatten back to a single array

**Generalization to N keys with mixed directions:**
For keys k1 (asc), k2 (desc), k3 (asc):
```jq
sort_by(.k3) |                          # innermost: ascending (last sort key)
# for descending keys, reverse before grouping
# This gets complex; for 2 keys the pattern above is sufficient
```

For the common 2-key case (primary asc, secondary desc), the pattern above is reliable and tested.

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
