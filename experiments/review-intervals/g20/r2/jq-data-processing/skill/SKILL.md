---
name: jq-data-processing
description: >
  Transform JSON data files using jq pipelines with filtering, normalization,
  field reshaping, aggregation, and multi-key sorting. Produces a jq filter,
  a YAML argument manifest, and a shell command script. Handles case-insensitive
  comparisons, null/default fallbacks, nested output structures, and
  mixed ascending/descending sort orders.
---

# jq Data Processing Skill

## Overview

This skill covers transforming JSON array data into structured reports using `jq`.
The general pattern is: **filter → normalize → reshape → aggregate → sort → output**.
Each task specifies selection criteria, output schema, value normalization rules,
and sort order. The deliverables are: the output JSON file, a `cmd.sh` script, and
a `jq_args.yaml` manifest.

## Quick Start Procedure

When approaching a new jq-data-processing task:

1. **Read the task specification carefully** — identify:
   - Selection criteria (which records to include/exclude)
   - Output schema (what fields, what structure)
   - Normalization rules (trim, lowercase, extract, default values)
   - Sort order (which keys, ascending/descending)

2. **Inspect the input data** — use `jq '.[0]' input.json` to see structure

3. **Build the filter incrementally** following the pipeline pattern:
   - Stage 1: Filter records with `select()`
   - Stage 2: Normalize values, derive fields, build output objects
   - Stage 3: Sort (use group-then-reverse for mixed ascending/descending)

4. **Test the filter** — `jq -f filter.jq input.json > reference.json`

5. **Create deliverables**:
   - `jq_args.yaml` with block scalar filter and `args: []`
   - `cmd.sh` with the reconstruction command

6. **Verify round-trip** — `diff reference.json output.json`

7. **Validate YAML constraint** — ensure all args items start with `-`

## General Pipeline Architecture

Every task follows this structural pattern in the jq filter:

```
[.[] | select(<selection_predicate>)] |       # Stage 1: Filter records
[.[] |                                         # Stage 2: Per-record transform
  <normalize values> |
  <derive output fields> |
  <build output object>
] |
<sort_expression>                              # Stage 3: Final ordering
```

### Stage 1: Selection

Common selection patterns:

- **Single field match**: `select(.status == "active")`
- **Multi-condition predicate**: `select(.status == "active" and (.roles | any(. == "admin")))`
- **Exclusion logic**: `select(.blocked_domains | any(. == $email_domain) | not)`
- **Derived value selection**: compute a value first, then filter on it
- **Combining inclusion and exclusion**: `select($has_privileged and ($is_blocked | not))`

Key technique: compute intermediate values with `as $var` bindings before the `select`,
so the predicate stays readable.

### Stage 2: Per-Record Transform

Within each record, the typical sub-steps are:

1. **Normalize inputs** — trim whitespace, lowercase, extract parts
2. **Derive computed values** — counts, membership checks, formatted strings
3. **Build output object** — map input fields to output schema

#### Value Normalization Patterns

| Need | jq Technique |
|------|-------------|
| Trim whitespace | `gsub("^\\s+|\\s+$"; "")` |
| Lowercase | `ascii_downcase` |
| Trim + lowercase | `gsub("^\\s+|\\s+$"; "") \| ascii_downcase` |
| Extract email domain | `split("@") \| .[1] \| ascii_downcase` |
| Extract date from ISO 8601 | `split("T")[0]` |
| Extract substring by pattern | `capture("(?<part>...)")` or `split` + index |
| Numeric coercion | `tonumber` |
| Boolean derivation | `(. == "value")` or `any(...)` |

#### Null and Default Handling

```jq
# String field: null or blank → default
if .field == null or (.field | gsub("^\\s+|\\s+$"; "") == "") then "default"
else (.field | gsub("^\\s+|\\s+$"; ""))
end

# Generic null fallback
.field // "default"

# Null propagation (keep null as null)
if .field == null then null else (.field | transform) end
```

#### Field Derivation Patterns

- **Rename**: `user_id: .id`
- **Keep as-is**: `username: .username`
- **Composite string**: `contact: "\(.username) <\(.email)>"`
- **Nested output object**:
  ```jq
  account_summary: {
    role_count: ($roles | length),
    primary_role: ($roles[0] // null),
    roles: $roles
  }
  ```
- **Deep field access**: `.metadata.tags[0].name`
- **Optional nested objects**: `.address // {} | .city // "unknown"`

### Stage 3: Aggregation & Collection Operations

| Operation | jq Technique |
|-----------|-------------|
| Deduplicate + sort | `unique` (returns sorted unique array) |
| Count items | `length` |
| First item | `.[0]` |
| First or null | `if length > 0 then .[0] else null end` or `.[0] // null` |
| Group records | `group_by(.field)` |
| Flatten nested arrays | `[.[][]]` or `add` |
| Sum over group | `map(.amount) | add` |
| Cross-record aggregation | `group_by(.key) | map({key: .[0].key, total: (map(.value) | add)})` |

### Stage 4: Sorting

#### Single-key ascending
```jq
sort_by(.field)
```

#### Multi-key ascending
```jq
sort_by(.field1, .field2)
```

#### Mixed ascending/descending (the hard case)

jq's `sort_by` only sorts ascending. For mixed orders, use the **group-then-reverse** pattern:

```jq
# Sort by field1 ascending, field2 descending:
group_by(.field1) |
[.[] | sort_by(.field2) | reverse] |
[.[][]]
```

This groups by the primary key (which `group_by` sorts ascending), then within each
group sorts by the secondary key and reverses for descending order, then flattens.

For more than 2 keys with mixed directions, nest the group-by pattern or compute
a composite sort key (e.g., negate numbers: `sort_by(.field1, (-.field2))`).

## Deliverable Production

### jq_args.yaml

The YAML manifest must contain exactly:
- `filter`: a string with the jq filter expression
- `args`: a list of strings where **each item must start with `-`** (a flag)

**Critical constraint**: The test validates `arg.startswith("-")` for every args item.
Since jq does not support `--flag=value` syntax (only `--flag value` as separate arguments),
flags with values cannot be expressed as single list items. Therefore, **the args list
should typically be empty** (`args: []`), and any configuration should be embedded in
the filter itself.

**Use YAML block scalar (`|`) for the filter** to avoid escaping hell:

```yaml
filter: |
  [.[] | select(.status == "active")] |
  [.[] |
    ... complex filter with "quotes", \(.interpolation), and regex ...
  ]
args: []
```

A block scalar treats content as literal text — no YAML escape processing. This
preserves double quotes, backslashes in regex, and string interpolation syntax intact.

**Why `args: []` is usually correct**:
- jq 1.6 defaults to 2-space indentation, so `--indent 2` is unnecessary
- Flags like `--arg name value` require separate positional arguments, which violates
  the `startswith("-")` constraint
- The filter expression itself can handle most transformations without external variables

**If you must use flags**: Only flags that take no value (like `--raw-output`, `--compact-output`)
can be used. Each such flag is a single list item:
```yaml
args:
  - "--raw-output"
```

**Never** attempt to use `--indent`, `--arg`, `--argjson`, etc. in the args list — they
require separate value arguments that cannot satisfy the `startswith("-")` constraint.

### cmd.sh

Must contain the exact reconstruction command including redirection:
```bash
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/users.json > /app/verified_admin_contacts.json
```

The `$(yq -r '.args[]' ...)` expands each args list item as a separate word.
The `"$(yq -r '.filter' ...)"` must be double-quoted to preserve the filter as one argument.

### Round-Trip Verification

**Always test the full reconstruction before declaring success:**

```bash
# 1. Produce reference output directly
jq -f /tmp/my_filter.jq input.json > /tmp/reference.json

# 2. Run the YAML round-trip
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" input.json > /tmp/roundtrip.json

# 3. Diff
diff /tmp/reference.json /tmp/roundtrip.json
```

This catches YAML escaping corruption — the most common failure mode.

## Common Pitfalls

### 1. Case sensitivity in comparisons
**Problem**: Comparing values without normalizing both sides.
**Example**: Email domain `"example.com"` vs blocked domain `"EXAMPLE.COM"` — must lowercase both.
**Solution**: Always normalize both sides before comparison:
```jq
(.email | split("@") | .[1] | ascii_downcase) as $domain |
(.blocked_domains[] | ascii_downcase) as $blocked |
select($domain == $blocked)
```

### 2. Whitespace in string values
**Problem**: Values like `" admin "` and `"admin"` are different strings.
**Solution**: Always trim before comparison or deduplication:
```jq
.roles[] | gsub("^\\s+|\\s+$"; "") | ascii_downcase
```

### 3. Null vs blank vs missing
**Problem**: Different representations of "no value":
- `null` (JSON null)
- `""` (empty string)
- `"   "` (whitespace only)
- Field missing entirely

**Solution**: Handle all cases explicitly:
```jq
if .phone == null or (.phone | gsub("^\\s+|\\s+$"; "") == "") then "unknown"
else (.phone | gsub("^\\s+|\\s+$"; ""))
end
```

### 4. Deduplication before normalization
**Problem**: Using `unique` on raw values — `"Admin"` and `"admin"` are different.
**Solution**: Normalize FIRST, then deduplicate:
```jq
[.roles[] | gsub("^\\s+|\\s+$"; "") | ascii_downcase] | unique
```

### 5. Mixed ascending/descending sort
**Problem**: `sort_by(.field1, .field2)` sorts both ascending.
**Solution**: Use group-then-reverse pattern:
```jq
group_by(.field1) |           # Groups sorted ascending by field1
[.[] | sort_by(.field2) | reverse] |  # Within each group, sort field2 descending
[.[][]]                        # Flatten
```

### 6. YAML escaping corruption
**Problem**: Filter contains quotes, backslashes, or interpolation that gets corrupted in YAML.
**Solution**: Use block scalar (`|`) for the filter value:
```yaml
filter: |
  [.[] | select(.status == "active")]
```
Block scalars treat content as literal — no escape processing.

### 7. Args format violation
**Problem**: Test requires every args item to start with `-`.
**Solution**: Use `args: []` for self-contained filters. Never use `["--indent", "2"]`.

### 8. ISO 8601 date extraction
**Problem**: Timestamps like `"2026-03-16T05:01:40.829540Z"` need date-only output.
**Solution**: Split on `"T"` and take first part:
```jq
.last_login | split("T")[0]   # Returns "2026-03-16"
```

## Debugging Checklist

When output is wrong, check these in order:

1. **Selection**: Are the right records included/excluded? Test with `jq '[.[] | select(...)] | length'`
2. **Normalization**: Are values correctly trimmed/lowercased? Test individual normalization on sample records
3. **Comparison**: Are case-insensitive comparisons done on BOTH sides? (e.g., both email domain and blocked domains must be lowercased)
4. **Deduplication**: Is `unique` applied after normalization? (Otherwise "Admin" and "admin" are different)
5. **Null handling**: Are null/blank values correctly defaulted? Check with `jq '[.[] | select(.field == null)]'`
6. **Sort order**: Is the sort stable and correct? Verify with `jq '[.[].field] | . as $orig | sort | . == $orig'`
7. **YAML escaping**: Does the round-trip match the direct filter? This is the #1 deliverable failure.
8. **Args format**: Does every item in `args` start with `-`? Validate with:
   ```python
   import yaml
   with open('jq_args.yaml') as f:
       config = yaml.safe_load(f)
   for arg in config['args']:
       assert arg.startswith('-'), f"Bad arg: {arg}"
   ```

## Spec Axis Coverage

This skill handles variation across four dimensions:

### selection_and_ordering_logic
- Single and multi-condition predicates
- Inclusion and exclusion logic across fields
- Selection based on derived/computed values
- Multi-key sorting with mixed ascending/descending

### field_derivation_and_reshaping
- Field renaming and flat output
- Nested output objects and arrays
- Composite field construction (string interpolation)
- Deep field access and optional nested objects
- Output structure differing from input

### value_normalization
- Whitespace trimming and case normalization
- Structured string extraction (email domains, dates)
- Numeric and boolean coercion
- Null propagation and fallback defaults
- Per-value formatting rules

### aggregation_and_collection_operations
- Per-record deduplication and counting
- Grouping records by key
- Aggregation over subsets (sum, count, etc.)
- Flattening and rebuilding arrays
- Combining per-record transform with cross-record aggregation
