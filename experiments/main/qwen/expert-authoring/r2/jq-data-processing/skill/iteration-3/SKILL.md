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

Tasks in this family transform a JSON input file into a JSON output file using
**jq** exclusively (no Python/Ruby). Every task requires saving three artifacts:

1. **Output JSON** – the transformed data, pretty-printed with 2-space indent
   (jq 1.6 default — no `--indent` flag needed).
2. **`/app/cmd.sh`** – executable shell command that regenerates the output.
3. **`/app/jq_args.yaml`** – YAML with `filter` (jq expression) and `args`
   (list of jq CLI arguments). Must work with the reconstruction command:
   ```
   jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" <input> > <output>
   ```

---

## Execution Workflow

Follow these five phases in order. Do not skip — each catches different errors.

### Phase 1: Explore (1–2 batched calls)

Read `task.yaml`, then gather all input characteristics in **one shell call**:

```bash
INPUT=/app/users.json  # adjust to actual input file
echo "=== Shape ===" && jq '.[0]' "$INPUT"
echo "=== Keys ===" && jq '.[0] | keys' "$INPUT"
echo "=== Count ===" && jq 'length' "$INPUT"
echo "=== Statuses ===" && jq '[.[].status] | unique' "$INPUT"
echo "=== Nulls ===" && jq '{null_phones: [.[] | select(.phone == null)] | length}' "$INPUT"
echo "=== Value distributions ===" && jq '[.[].roles[]] | unique' "$INPUT"
```

Adapt field names to the actual task. The goal is to understand the schema,
identify null/edge cases, and know what normalization is needed — all in one
call.

### Phase 2: Build filter in /tmp/filter.jq

Write the jq filter to a temp file using a **single-quoted heredoc** (this
prevents bash from expanding `$variables` or interpreting backslashes):

```bash
cat > /tmp/filter.jq << 'JQEOF'
[.[] |
  # Normalize and bind intermediates
  ... as $var |
  # Filter
  select(...) |
  # Reshape
  { ... }
] | sort_by(...)
JQEOF
```

Test it:
```bash
jq -f /tmp/filter.jq "$INPUT" | jq 'length'
jq -f /tmp/filter.jq "$INPUT" | jq '.[0]'
```

Iterate on the filter here until output is correct. **Never debug in cmd.sh
or jq_args.yaml** — fix in `/tmp/filter.jq`, then regenerate artifacts.

### Phase 3: Single-pass verification

Run **one comprehensive verification script** that checks all requirements:

```bash
jq -f /tmp/filter.jq "$INPUT" > /tmp/output.json
cat << 'VERIFY' > /tmp/verify.jq
{
  record_count: length,
  fields: (.[0] | keys),
  sort_violations: ([. as $a | range(0; length-1) |
    if $a[.].KEY1 > $a[.+1].KEY1 then "BAD_K1"
    elif $a[.].KEY1 == $a[.+1].KEY1 and $a[.].KEY2 < $a[.+1].KEY2 then "BAD_K2"
    else empty end] | length),
  untrimmed_phones: ([.[] | .phone | select(test("^\\s|\\s$"))] | length),
  unknown_phones: ([.[] | select(.phone == "unknown")] | length),
  bad_dates: ([.[].last_login | select(test("^\\d{4}-\\d{2}-\\d{2}$") | not)] | length)
}
VERIFY
jq -f /tmp/verify.jq /tmp/output.json
```

Replace `KEY1`/`KEY2` and field names with the actual task requirements.
Add checks specific to the task (excluded records, normalization, etc.).
All counts except `record_count` should be 0.

### Phase 4: Create artifacts

**Generate output:**
```bash
jq -f /tmp/filter.jq "$INPUT" > /app/output.json
```

**Create cmd.sh** using `jq -f /tmp/filter.jq` — this avoids shell-quoting
nightmares with complex filters:
```bash
cat > /app/cmd.sh << 'CMDEOF'
jq -f /tmp/filter.jq /app/input.json > /app/output.json
CMDEOF
chmod +x /app/cmd.sh
```
Then copy the filter file to its permanent location:
```bash
cp /tmp/filter.jq /app/filter.jq
```
And update cmd.sh to reference the permanent path:
```bash
cat > /app/cmd.sh << 'CMDEOF'
jq -f /app/filter.jq /app/input.json > /app/output.json
CMDEOF
chmod +x /app/cmd.sh
```

> **Alternative: inline filter in cmd.sh.** If the task says cmd.sh must
> contain the full jq command without referencing external files, use a
> single-quoted string in a heredoc:
> ```bash
> cat > /app/cmd.sh << 'CMDEOF'
> jq '[.[] | ... ]' /app/input.json > /app/output.json
> CMDEOF
> ```
> Single quotes prevent bash interpretation. Works for simple filters but
> fragile for filters containing single quotes themselves.

**Create jq_args.yaml** using a single-quoted heredoc + YAML literal block:
```bash
cat > /app/jq_args.yaml << 'YAMLEOF'
filter: |
  [.[] |
    ... multi-line filter ...
  ] | sort_expression
args: []
YAMLEOF
```
- `'YAMLEOF'` prevents bash expansion
- `|` (literal block scalar) preserves `\s`, `\(`, `$var` verbatim
- `yq -r '.filter'` outputs the raw string for jq to interpret
- When `args` is non-empty, list each flag and value separately:
  `args: ["--arg", "name", "value"]`

### Phase 5: End-to-end validation (single call)

Test all three paths in **one shell call**:

```bash
# 1. cmd.sh replay
rm -f /app/output.json
bash /app/cmd.sh
CMD_COUNT=$(jq length /app/output.json)

# 2. YAML reconstruction
cp /app/output.json /tmp/from_cmd.json
rm -f /app/output.json
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" "$INPUT" > /app/output.json
YAML_COUNT=$(jq length /app/output.json)

# 3. Compare
diff <(jq -c '.' /tmp/from_cmd.json) <(jq -c '.' /app/output.json) && MATCH="IDENTICAL" || MATCH="DIFFERENT"

echo "cmd.sh: $CMD_COUNT records | YAML: $YAML_COUNT records | $MATCH"
```

All three must agree. If not, fix `/tmp/filter.jq` and regenerate.

---

## Problem Decomposition

Break the task into four concerns, solve independently, compose into one
pipeline.

### 1. Selection and Ordering

| Situation | jq idiom |
|---|---|
| Single filter | `select(.field == "value")` |
| Multi-condition AND | Chain `select(...)` or use `and` |
| Multi-condition OR | `select(.a == "x" or .b == "y")` |
| Exclusion | `select(condition \| not)` |
| Filter on derived value | `as $var`, then `select` on `$var` |
| Sort ascending | `sort_by(.key)` |
| Sort descending | `sort_by(.key) \| reverse` |
| Multi-key mixed direction | `group_by(.k1) \| map(sort_by(.k2) \| reverse) \| flatten` |
| Multi-key all ascending | `sort_by(.k1, .k2)` |

**Always normalize before filtering.** Bind normalized values with `as $var`
first, then `select` on `$var`.

### 2. Field Derivation and Reshaping

| Situation | jq idiom |
|---|---|
| Rename | `{new_name: .old_name}` |
| Keep as-is | `{username}` (shorthand) |
| Combine to string | `"\(.a) <\(.b)>"` |
| Nested access | `.parent.child` or `.parent // {} \| .child` |
| Array element | `.arr[0]` or `.arr \| first` |
| Nested output | `{summary: {count: ..., list: ...}}` |
| Conditional | `if COND then A else B end` |

### 3. Value Normalization

| Normalization | jq expression |
|---|---|
| Trim whitespace | `gsub("^\\s+\|\\s+$"; "")` |
| Lowercase | `ascii_downcase` |
| Trim + lowercase | `gsub("^\\s+\|\\s+$"; "") \| ascii_downcase` |
| ISO 8601 → YYYY-MM-DD | `split("T")[0]` |
| Extract email domain | `split("@")[1] \| ascii_downcase` |
| Null → default | `. // "default"` |
| Null/blank → default | `(. // "" \| gsub("^\\s+\|\\s+$"; "")) \| if . == "" then "default" else . end` |
| Numeric coercion | `tonumber` / `tostring` |

**Order:** normalize → deduplicate (`unique`) → sort (`sort`) → use.

**Null safety:** `// []` for arrays, `// ""` for strings (before gsub),
`// {}` for objects.

### 4. Aggregation and Collection

| Operation | jq idiom |
|---|---|
| Count / unique count | `length` / `unique \| length` |
| Deduplicate | `unique` (also sorts) |
| Group | `group_by(.key)` |
| Aggregate per group | `group_by(.k) \| map({k: .[0].k, n: length})` |
| Flatten | `flatten` or `[.[][]]` |
| Membership test | `$arr \| any(. == $val)` or `($arr \| index($val)) != null` |
| Cross-record sum/max | `[.[] \| .field] \| add` / `map \| max` |

---

## Pipeline Assembly

Build in this order: bind → filter → reshape → wrap → sort.

```jq
[.[] |
  # 1. Bind normalized intermediates
  (.arr_field // [] | map(NORM) | unique) as $norm_arr |
  (.src_field | EXTRACT) as $derived |
  (.list_field // [] | map(NORM)) as $norm_list |
  (.opt_field // "" | CLEANUP) as $cleaned |
  # 2. Filter
  select(.status == "REQUIRED") |
  select($norm_arr | any(PREDICATE)) |
  select(($norm_list | index($derived)) == null) |
  # 3. Reshape
  {
    out1: .src1,
    out2: $derived,
    out3: (if $cleaned == "" then "DEFAULT" else $cleaned end),
    nested: {
      count: ($norm_arr | length),
      first: ($norm_arr | sort | if length == 0 then null else .[0] end),
      list: ($norm_arr | sort)
    }
  }
] | SORT_EXPRESSION
```

---

## Robustness Against Input Variations

Tests may modify input data and re-run saved commands. Ensure:

- **No hardcoded values** — filter must work for any schema-conforming data.
- **Defensive null handling** — `// []`, `// ""`, `// {}` before operations.
- **Empty array guards** — `if length == 0 then null else .[0] end`.
- **Varying record counts** — filter works for 0 to 10000+ records.
- **Stateless** — no external variables, temp files, or prior state.

---

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| `sort_by(.a, .b)` both ascending | `group_by(.a) \| map(sort_by(.b) \| reverse) \| flatten` for mixed |
| `\s` mangled by YAML/shell | Single-quoted heredoc + literal block scalar `\|` |
| `select` on null field | Guard with `// []` or `// ""` first |
| `\(...)` in YAML double-quotes | Use literal block scalar |
| Normalize after comparing | Bind with `as $var` before `select` |
| JSON null field crashes gsub | `(.field // "" \| gsub(...))` |
| `group_by` on non-array | Collect with `[...]` first |
| Heredoc without quotes expands `$var` | Always `'TAG'` (single-quoted) |
| Debugging in cmd.sh/yaml | Fix in `/tmp/filter.jq`, regenerate |
| `--indent 2` flag | Not needed — jq 1.6 default is 2-space |
| Inline filter with single quotes | Use `jq -f file.jq` approach instead |
