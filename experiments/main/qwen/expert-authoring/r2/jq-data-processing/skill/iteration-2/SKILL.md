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

## Execution Workflow

Follow this step-by-step workflow to build, test, and deploy the jq filter.
Do not skip steps — each catches a different class of errors.

### Phase 1: Explore

1. Read `task.yaml` to understand the exact requirements.
2. Inspect the input JSON structure:
   ```bash
   jq '.[0]' /app/input.json          # first record shape
   jq '.[0] | keys' /app/input.json   # field names
   jq 'length' /app/input.json        # record count
   jq '[.[].some_field] | unique' /app/input.json  # value distribution
   ```
3. Identify which fields may be `null`, missing, or need normalization by
   checking for edge cases:
   ```bash
   jq '[.[] | select(.phone == null)] | length' /app/input.json
   jq '[.[].roles[]] | unique' /app/input.json
   ```

### Phase 2: Build the filter in a temp file

Write the jq filter to `/tmp/filter.jq` using a heredoc. This avoids all
shell-quoting and YAML-escaping issues during development:

```bash
cat > /tmp/filter.jq << 'JQEOF'
[.[] |
  # Step 1: Normalize and bind intermediates
  ... as $var1 |
  ... as $var2 |
  # Step 2: Filter
  select(...) |
  select(...) |
  # Step 3: Reshape
  { ... }
] | <sort expression>
JQEOF
```

Then test it:
```bash
jq -f /tmp/filter.jq /app/input.json | jq 'length'
jq -f /tmp/filter.jq /app/input.json | jq '.[0]'
```

### Phase 3: Verify the output

Run verification queries against the output to check every requirement:
```bash
jq -f /tmp/filter.jq /app/input.json > /tmp/output.json

# Check all required fields present
jq '[.[0] | keys]' /tmp/output.json

# Check sort order (no violations should appear)
jq '[. as $a | range(0; length-1) |
  if $a[.].key1 > $a[.+1].key1 then "BAD" else empty end] | length' /tmp/output.json

# Check normalization (no trailing whitespace, correct case)
jq '[.[] | .field | select(test("^\\s|\\s$"))] | length' /tmp/output.json

# Check excluded records don't appear
jq '[.[] | select(.field == "should_be_excluded")] | length' /tmp/output.json

# Check null/default handling
jq '[.[] | select(.field == "default_value")] | length' /tmp/output.json
```

### Phase 4: Create artifacts

**Produce the final output:**
```bash
jq -f /tmp/filter.jq /app/input.json > /app/output.json
```

**Create jq_args.yaml** using a quoted heredoc (`'YAMLEOF'`) with a YAML
literal block scalar (`|`):
```bash
cat > /app/jq_args.yaml << 'YAMLEOF'
filter: |
  [.[] | ... your filter here ...]
args: []
YAMLEOF
```
The `|` preserves all backslashes, dollar signs, and quotes literally.
The quoted heredoc `'YAMLEOF'` prevents bash from interpreting `$var` or
backticks. The filter may span multiple lines — jq accepts multi-line
filters from `yq -r`.

**Create cmd.sh** with the inline single-line filter:
```bash
cat > /app/cmd.sh << 'CMDEOF'
jq '<single-line filter>' /app/input.json > /app/output.json
CMDEOF
chmod +x /app/cmd.sh
```

### Phase 5: End-to-end validation

**This is the critical step.** Test both artifact paths independently:

```bash
# Test 1: cmd.sh replay
rm /app/output.json
bash /app/cmd.sh
echo "cmd.sh records: $(jq length /app/output.json)"

# Test 2: YAML reconstruction replay
rm /app/output.json
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/input.json > /app/output.json
echo "YAML reconstruction records: $(jq length /app/output.json)"

# Test 3: Compare both outputs byte-for-byte
cp /app/output.json /tmp/from_yaml.json
bash /app/cmd.sh
diff <(jq -c '.' /app/output.json) <(jq -c '.' /tmp/from_yaml.json) && echo "IDENTICAL" || echo "DIFFERENT"
```

If tests fail, debug the filter in `/tmp/filter.jq`, fix, then re-create
artifacts. Never edit `cmd.sh` or `jq_args.yaml` directly — regenerate from
the working filter.

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
| Multi-key mixed direction | `group_by(.asc_key) \| map(sort_by(.desc_key) \| reverse) \| flatten` |
| Fully ascending multi-key | `sort_by(.key1, .key2)` |

**Key pattern – mixed ascending/descending sort:**

jq's `sort_by` is always ascending. For descending on a secondary key:
```jq
group_by(.asc_key) | map(sort_by(.desc_key) | reverse) | flatten
```
`group_by` already sorts groups ascending by the grouping key. Within each
group, sort ascending then reverse for descending.

**Pitfall:** Always normalize values *before* using them in select predicates.
If the task says "trim and lowercase before checking," compute the normalized
form first, bind it with `as $var`, then filter on `$var`.

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

### 3. Value Normalization

**What to decide:** What scalar transformations to apply to individual values.

**Common normalizations and their jq implementations:**

| Normalization | jq expression |
|---|---|
| Trim whitespace | `gsub("^\\s+\|\\s+$"; "")` |
| Lowercase | `ascii_downcase` |
| Trim + lowercase | `gsub("^\\s+\|\\s+$"; "") \| ascii_downcase` |
| ISO 8601 → YYYY-MM-DD | `split("T")[0]` |
| ISO 8601 → date parts | `split("T")[0] \| split("-")` then index parts |
| Extract domain from email | `split("@")[1] \| ascii_downcase` |
| Null → default | `. // "default"` (works when value is null) |
| Null-or-blank → default | `if . == null or (type == "string" and (. \| gsub("^\\s+\|\\s+$"; "")) == "") then "default" else . end` |
| Trim + blank → default | `gsub("^\\s+\|\\s+$"; "") \| if . == "" then "default" else . end` |
| Numeric coercion | `tonumber` (string→number), `tostring` (number→string) |
| Boolean derivation | `if .score > 80 then true else false end` |

**Critical ordering rule:** Always normalize *before* comparison, deduplication,
or sorting. The typical sequence is:
1. Normalize (trim, lowercase, coerce)
2. Deduplicate (`unique`)
3. Sort (`sort`)
4. Use in predicates or output

**Null safety patterns:**
- Arrays that might be null: `(.roles // [] | map(...))`
- Strings that might be null: `(.phone // "" | gsub(...))` — coerce null to
  empty string *before* string operations like `gsub`
- Objects that might be null: `.data // {} | .nested_field`

### 4. Aggregation and Collection Operations

**What to decide:** How to summarize, group, or reorganize data across records.

**Decision rules:**

| Operation | jq idiom |
|---|---|
| Count items | `length` |
| Count unique values | `unique \| length` |
| Deduplicate array | `unique` (also sorts) |
| Sort array | `sort` |
| First element of sorted | `sort \| .[0]` or `sort \| first` |
| Group records | `group_by(.key)` |
| Aggregate per group | `group_by(.key) \| map({key: .[0].key, count: length})` |
| Flatten nested arrays | `flatten` or `[.[][]]` |
| Cross-record summary | `[.[] \| .field] \| add` (sum), `map \| max`, etc. |
| Check membership in array | `($arr \| index($val)) != null` or `($arr \| any(. == $val))` |
| Slurp all input | Use `-s` flag or wrap filter in `[inputs]` |

---

## Pipeline Assembly Order

Build the jq filter in this order (each step depends on the previous):

1. **Bind normalized intermediates** with `as $var` expressions.
2. **Filter** with `select(...)` predicates.
3. **Reshape** into the output record structure.
4. **Wrap** in `[.[] | ...]` to produce an output array.
5. **Sort** the output array.

**Generic template:**
```jq
[.[] |
  # Step 1: Normalize and bind intermediates
  (.array_field // [] | map(NORMALIZE_FN) | unique) as $norm_arr |
  (.source_field | EXTRACT_FN) as $derived |
  (.list_field // [] | map(NORMALIZE_FN)) as $norm_list |
  (.optional_field // "" | CLEANUP_FN) as $cleaned |
  # Step 2: Filter
  select(.status_field == "REQUIRED_STATUS") |
  select($norm_arr | any(PREDICATE)) |
  select(($norm_list | index($derived)) == null) |
  # Step 3: Reshape
  {
    output_field1: .source_field1,
    output_field2: $derived,
    output_field3: (if $cleaned == "" then "DEFAULT" else $cleaned end),
    nested_object: {
      count: ($norm_arr | length),
      first: ($norm_arr | sort | if length == 0 then null else .[0] end),
      list: ($norm_arr | sort)
    }
  }
# Step 4-5: Sort the collected array
] | SORT_EXPRESSION
```

---

## YAML Serialization for jq_args.yaml

The filter string contains backslashes (`\s`, `\(`), double quotes, and dollar
signs. Use a YAML **literal block scalar** (`|`) inside a **quoted heredoc**
(`'YAMLEOF'`) to avoid escaping issues:

```bash
cat > /app/jq_args.yaml << 'YAMLEOF'
filter: |
  [.[] |
    (.roles // [] | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase) | unique) as $norm_roles |
    ...
  ] | group_by(.key) | map(sort_by(.key2) | reverse) | flatten
args: []
YAMLEOF
```

**Why this works:**
- `'YAMLEOF'` (single-quoted) prevents bash from expanding `$norm_roles` or
  interpreting backslashes inside the heredoc.
- `|` (literal block scalar) tells YAML to preserve all content verbatim,
  including `\s` and `\\(`.
- `yq -r '.filter'` reads the YAML and outputs the raw string, which jq
  then interprets — `\s` becomes a regex whitespace class, `\(` starts
  string interpolation, etc.

**When `args` is non-empty:**
```yaml
args: ["--arg", "threshold", "80", "--slurpfile", "config", "/app/config.json"]
```
Each flag and its value should be separate list items. `$(yq -r '.args[]' ...)`
word-splits them correctly in the reconstruction command.

**When `args` is empty:** `$(yq -r '.args[]' ...)` expands to nothing, which
is harmless.

---

## Robustness Against Input Variations

Tests may modify the input data and re-run saved commands. Ensure:

1. **No hardcoded values from the input data** in the filter — the filter
   must work for any data conforming to the schema.
2. **Handle missing/null fields defensively** — use `// []`, `// ""`,
   `// {}` before operations that would fail on null.
3. **Handle empty arrays** — `unique` on `[]` returns `[]`; `sort | .[0]`
   on `[]` returns `null`. Guard with `if length == 0 then null else .[0] end`.
4. **Handle varying record counts** — the filter should work whether the
   input has 0, 1, or 10000 records.
5. **The filter itself must be stateless** — no reliance on external
   variables, temp files, or prior state beyond the input JSON.

---

## Verification Checklist

After generating output, verify these invariants using jq itself:

1. **Record count:** `jq length output.json` — matches expected filtering?
2. **Required fields:** `jq '[.[0] | keys]' output.json` — all expected keys?
3. **Sort order:** Walk adjacent pairs and check the sort predicate holds:
   ```jq
   [. as $a | range(0; length-1) |
     if $a[.].key1 > $a[.+1].key1 then "BAD" else empty end] | length
   ```
4. **No excluded records leaked:** Query for records that should have been
   filtered out and confirm count is 0.
5. **Normalization applied:** No leading/trailing whitespace or wrong case:
   ```jq
   [.[] | .field | select(test("^\\s|\\s$"))] | length   # should be 0
   ```
6. **Null/default handling:** Null/missing source values produce the
   specified default.
7. **Reproducibility:** `rm output.json && bash /app/cmd.sh` produces
   identical output.
8. **Reconstruction:** The exact `jq $(yq ...) "$(yq ...)" input > output`
   command produces identical output.
9. **Both paths agree:** `diff <(jq -c '.' /app/output.json) <(jq -c '.' /tmp/yaml_output.json)` shows no differences.

---

## Common Pitfalls

| Pitfall | How to avoid |
|---|---|
| `sort_by(.a, .b)` sorts both ascending | Use `group_by(.a) \| map(sort_by(.b) \| reverse) \| flatten` for mixed directions |
| `unique` sorts the array | If original order matters, use a different dedup strategy |
| `gsub` with `\s` gets mangled by YAML or shell | Use quoted heredoc `'EOF'` + literal block scalar `\|` |
| `select` on null field errors | Guard with `// []` or `// ""` before select |
| String interpolation `\(...)` inside YAML double-quoted strings | Use literal block scalar to keep `\(` literal for jq |
| Forgetting to normalize before comparing | Always bind normalized values with `as $var` before any `select` |
| Phone/field is JSON `null` (not string) | Use `(.field // "" \| cleanup)` — coerce null before string ops |
| `group_by` requires array input | Ensure the pipeline collects into `[...]` before grouping |
| `yq -r '.args[]'` with empty args list | Expands to nothing — this is correct and harmless |
| Bash heredoc without quotes expands `$var` | Always use `'HEREDOC_TAG'` (single-quoted) for jq filters |
| Editing cmd.sh or jq_args.yaml directly | Always regenerate from the working `/tmp/filter.jq` |
| Multi-key sort with all ascending | `sort_by(.key1, .key2)` works directly |
