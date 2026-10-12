---
name: jq-data-processing
description: >
  Systematic strategy for jq-based JSON transformation tasks: reading structured
  JSON input, applying filtering, normalization, reshaping, and aggregation
  pipelines, then emitting formatted JSON output along with reproducible command
  artifacts (cmd.sh and jq_args.yaml).
---

# jq Data Processing

## Overview

Tasks in this family require transforming a JSON input file into a JSON output
file using **jq** exclusively (no Python/Ruby/other languages for the
transformation). Every task also requires saving:

1. **`/app/cmd.sh`** – the exact shell command that produces the output,
   including output redirection.
2. **`/app/jq_args.yaml`** – a YAML file with keys `filter` (the jq expression)
   and `args` (list of jq CLI arguments such as `--arg`, `--slurpfile`, or
   formatting flags). This file must be consumable by the reconstruction
   command:
   ```
   jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" <input> > <output>
   ```

---

## Problem Decomposition

Break every task into four independent concerns that map to the spec axes.
Solve each concern in isolation, then compose them into a single jq pipeline.

### 1. Selection and Ordering Logic

**What to decide:** Which records to include and how to sort the final output.

**Decision rules:**

| Situation | jq idiom |
|---|---|
| Single equality filter | `select(.field == "value")` |
| Multi-condition (AND) | Chain multiple `select(...)` or combine with `and` |
| Multi-condition (OR) | `select(.a == "x" or .b == "y")` |
| Exclusion / NOT | `select(.field != "value")` or `select(condition \| not)` |
| Filter on derived value | Compute derived value with `as $var`, then `select` on `$var` |
| Sort ascending by one key | `sort_by(.key)` |
| Sort descending by one key | `sort_by(.key) \| reverse` |
| Multi-key mixed direction | `group_by(.key1) \| map(sort_by(.key2) \| reverse) \| flatten` (ascending key1, descending key2) |
| Fully ascending multi-key | `sort_by(.key1, .key2)` |

**Key pattern – mixed ascending/descending sort:**

jq's `sort_by` is always ascending. For descending on a secondary key:
```jq
group_by(.asc_key) | map(sort_by(.desc_key) | reverse) | flatten
```
`group_by` already sorts groups ascending by the grouping key. Within each
group, sort ascending then reverse for descending.

**Pitfall:** Always normalize values *before* using them in select predicates.
If the task says "trim and lowercase roles before checking privileged status,"
compute the normalized form first, bind it with `as $var`, then filter on
`$var`.

### 2. Field Derivation and Reshaping

**What to decide:** How to build each output record from the input fields.

**Decision rules:**

| Situation | jq idiom |
|---|---|
| Rename a field | `{new_name: .old_name}` |
| Keep field as-is | `{username}` (shorthand for `{username: .username}`) |
| Combine fields into string | `"\(.field1) <\(.field2)>"` (string interpolation) |
| Access nested object | `.parent.child` or `.parent // {} \| .child` for optional |
| Access nested array element | `.arr[0]`, `.arr \| first` |
| Emit nested output object | `{summary: {count: ..., list: ...}}` |
| Derive from multiple sources | Bind each with `as $var`, compose in output object |
| Conditional field value | `if COND then VAL1 else VAL2 end` |

**Pattern – building a complex output record:**
```jq
{
  user_id: .id,
  username,
  email,
  email_domain: $email_domain,
  contact: "\(.username) <\(.email)>",
  phone: (if .phone == null or (.phone | gsub("^\\s+|\\s+$"; "")) == ""
          then "unknown"
          else (.phone | gsub("^\\s+|\\s+$"; "")) end),
  account_summary: {
    role_count: ($norm_roles | length),
    primary_role: ($norm_roles | sort | if length == 0 then null else .[0] end),
    roles: ($norm_roles | sort)
  }
}
```

### 3. Value Normalization

**What to decide:** What scalar transformations to apply to individual values.

**Common normalizations and their jq implementations:**

| Normalization | jq expression |
|---|---|
| Trim whitespace | `gsub("^\\s+\\|\\s+$"; "")` |
| Lowercase | `ascii_downcase` |
| Trim + lowercase | `gsub("^\\s+\\|\\s+$"; "") \| ascii_downcase` |
| ISO 8601 → YYYY-MM-DD | `split("T")[0]` |
| ISO 8601 → date parts | `split("T")[0] \| split("-")` then index year/month/day |
| Extract domain from email | `split("@")[1] \| ascii_downcase` |
| Null → default | `if . == null then "default" else . end` or `. // "default"` |
| Blank/Null → default | `if . == null or . == "" then "default" else . end` |
| Trim + blank → default | `gsub("^\\s+\\|\\s+$"; "") \| if . == "" then "default" else . end` |
| Numeric coercion | `tonumber` (string→number), `tostring` (number→string) |
| Boolean derivation | `if .score > 80 then true else false end` |

**Critical ordering rule:** Always normalize *before* comparison, deduplication,
or sorting. The typical sequence is:
1. Normalize (trim, lowercase, coerce)
2. Deduplicate (`unique`)
3. Sort (`sort`)
4. Use in predicates or output

**Null safety:** Use `// []` for arrays and `// {}` for objects that might be
null: `(.roles // [] | map(...))`.

### 4. Aggregation and Collection Operations

**What to decide:** How to summarize, group, or reorganize data across records.

**Decision rules:**

| Operation | jq idiom |
|---|---|
| Count items | `length` |
| Count unique values | `unique \| length` |
| Deduplicate array | `unique` |
| Sort array | `sort` |
| First element of sorted | `sort \| .[0]` or `sort \| first` |
| Group records | `group_by(.key)` |
| Aggregate per group | `group_by(.key) \| map({key: .[0].key, count: length})` |
| Flatten nested arrays | `[.[][] ]` or `flatten` |
| Cross-record summary | `[.[] \| .field] \| add` (sum), `map \| max`, etc. |
| Slurp all input | Use `-s` flag or wrap filter in `[inputs]` |

**Pattern – per-record collection + cross-record sort:**
```jq
[.[] |
  (.roles // [] | map(normalize) | unique) as $norm_roles |
  ... |
  { ..., role_count: ($norm_roles | length), roles: ($norm_roles | sort) }
] | group_by(.email_domain) | map(sort_by(.username) | reverse) | flatten
```

---

## Pipeline Assembly Order

Build the jq filter in this order (each step depends on the previous):

1. **Bind normalized intermediates** with `as $var` expressions.
2. **Filter** with `select(...)` predicates.
3. **Reshape** into the output record structure.
4. **Wrap** in `[.[] | ...]` to produce an output array.
5. **Sort** the output array.

**Template:**
```jq
[.[] |
  # Step 1: Normalize and bind intermediates
  (.roles // [] | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase) | unique) as $norm_roles |
  (.email | split("@")[1] | ascii_downcase) as $email_domain |
  # Step 2: Filter
  select(.status == "active") |
  select(($norm_roles | any(. == "admin" or . == "owner"))) |
  select(($blocked | index($email_domain)) == null) |
  # Step 3: Reshape
  { user_id: .id, ... }
# Step 4-5: Sort the collected array
] | group_by(.email_domain) | map(sort_by(.username) | reverse) | flatten
```

---

## YAML Serialization for jq_args.yaml

The filter string contains backslashes (`\s`, `\(`), double quotes, and dollar
signs. Use a YAML **literal block scalar** (`|`) to avoid escaping issues:

```yaml
filter: |
  [.[] | (.roles // [] | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase) | unique) as $norm_roles | ...]
args: []
```

- `|` preserves backslashes and special characters literally.
- jq ignores the trailing newline that `|` appends.
- When `args` is empty, `$(yq -r '.args[]' ...)` expands to nothing in the
  shell, which is harmless.
- When args are needed (e.g., `--arg name value`), list each as a separate
  string: `args: ["--arg", "myvar", "hello"]`.

---

## Verification Checklist

After generating output, verify these invariants using jq itself:

1. **Record count:** `jq length output.json` – does it match expected filtering?
2. **Required fields:** `jq '[.[0] | keys]' output.json` – all expected keys present?
3. **Sort order:** Walk adjacent pairs and check the sort predicate holds:
   ```jq
   [. as $all | range(0; length-1) |
     if $all[.].key1 > $all[.+1].key1 then "BAD_SORT" else empty end]
   ```
4. **No excluded records leaked:** Query for records that should have been
   filtered out and confirm count is 0.
5. **Normalization applied:** Spot-check that trimmed/lowercased values contain
   no leading/trailing whitespace or uppercase where lowercase is expected:
   ```jq
   [.[] | .field | select(test("^\\s|\\s$"))] | length   # should be 0
   ```
6. **Null/default handling:** Check that null/missing source values produce the
   specified default in the output.
7. **Reproducibility:** Run `bash /app/cmd.sh` from scratch (delete output
   first) and confirm the output is identical.
8. **Reconstruction:** Run the exact reconstruction command from the task
   spec and diff against the generated output.

---

## Common Pitfalls

| Pitfall | How to avoid |
|---|---|
| `sort_by(.a, .b)` sorts both ascending | Use `group_by` + `map(sort_by \| reverse)` for mixed directions |
| `unique` sorts the array | If original order matters, use a different dedup strategy |
| `gsub` with `\s` gets mangled by YAML | Use literal block scalar `\|` in YAML |
| `select` on null field errors | Guard with `// []` or `// ""` before select |
| String interpolation `\(...)` inside YAML double-quoted strings | Use literal block scalar to keep `\(` literal for jq |
| Forgetting to normalize before comparing | Always bind normalized values with `as $var` before any `select` |
| Phone/field is `null` (JSON null, not string) | Check `. == null` before string operations like `gsub` |
| `group_by` requires array input | Ensure the pipeline collects into `[...]` before grouping |
| `yq -r '.args[]'` with empty args list | Expands to nothing – this is correct and harmless |
