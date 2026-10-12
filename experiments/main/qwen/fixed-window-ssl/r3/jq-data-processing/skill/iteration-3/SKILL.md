---
name: jq-data-processing
description: >
  Transform JSON arrays of records using jq pipelines that combine multi-condition
  selection, field derivation/reshaping, value normalization, and aggregation.
  Handles complex predicates, mixed-direction sorting, nested output structures,
  and serialization of jq filters to YAML/config files.
---

# jq Data Processing

## Core Workflow

1. **Inspect the input schema** — identify record fields, nested arrays/objects, and data types
2. **Decompose the requirements** into four stages: selection, normalization, reshaping, aggregation
3. **Build the jq filter incrementally**, testing each stage
4. **Serialize to YAML/config** using block scalars to avoid escape hell
5. **Verify the round-trip** — reconstruct the command and diff against reference output

## Quick Start Template

Use this template as your starting point. Adapt each section to your specific requirements:

```jq
# Step 1: Define normalization functions (use if pattern appears 2+ times)
def normalize: gsub("^\\s+|\\s+$"; "") | ascii_downcase;
def extract_domain: split("@") | .[1] | ascii_downcase;
def extract_date: split("T") | .[0];

# Step 2: Build the transformation pipeline
[
  .[] |
  # Step 2a: Filter by status/conditions
  select(.status == "active") |
  
  # Step 2b: Normalize and bind intermediate values
  (.roles | map(normalize) | unique) as $norm_roles |
  (.email | extract_domain) as $email_domain |
  (.blocked_domains | map(normalize)) as $norm_blocked |
  
  # Step 2c: Apply inclusion/exclusion filters
  select([$norm_roles[] | select(. == "admin" or . == "owner")] | length > 0) |
  select([$norm_blocked[] | select(. == $email_domain)] | length == 0) |
  
  # Step 2d: Reshape output record
  {
    user_id: .id,
    username: .username,
    email: .email,
    email_domain: $email_domain,
    contact: "\(.username) <\(.email)>",
    phone: (
      if .phone == null then "unknown"
      elif (.phone | normalize | length) == 0 then "unknown"
      else (.phone | normalize)
      end
    ),
    last_login: (.last_login | extract_date),
    account_summary: {
      role_count: ($norm_roles | length),
      primary_role: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end),
      roles: $norm_roles
    }
  }
] |
# Step 3: Sort (use group_by for multi-key mixed-direction sorting)
group_by(.email_domain) |
map(sort_by(.username) | reverse) |
add // []
```

**Workflow checklist**:
- [ ] Identify all fields that need normalization → extract to `def`
- [ ] Identify filter conditions → chain as `select()` stages
- [ ] Identify intermediate values → bind with `as $var`
- [ ] Build output object referencing bound variables
- [ ] Determine sort order → use `group_by | map(sort_by | reverse) | add` for mixed directions
- [ ] Test with small sample before full run
- [ ] Serialize to YAML with block scalar (`|`)
- [ ] Verify round-trip with diff

## Recommended Pattern: Use `def` for Normalization

**Critical**: When any normalization logic (trim, lowercase, extract, etc.) appears more than once in your filter, define it as a `def` at the top. This is the single most important practice for writing maintainable, error-free jq pipelines.

```jq
# Define normalization functions at the top
def normalize: gsub("^\\s+|\\s+$"; "") | ascii_downcase;
def extract_domain: split("@") | .[1] | ascii_downcase;
def extract_date: split("T") | .[0];

[
  .[] |
  select(.status == "active") |
  # Use the defined functions consistently
  (.roles | map(normalize) | unique) as $norm_roles |
  (.email | extract_domain) as $email_domain |
  (.blocked_domains | map(normalize)) as $norm_blocked |
  # ... rest of pipeline
  {
    # Reuse normalize for phone field too
    phone: (if .phone == null then "unknown"
            elif (.phone | normalize | length) == 0 then "unknown"
            else (.phone | normalize)
            end)
  }
]
```

**Why this matters**:
- **DRY**: Write the normalization logic once, use it everywhere
- **Fewer bugs**: No risk of inconsistent normalization (e.g., forgetting to lowercase in one place)
- **Easier to maintain**: Change the normalization in one place if requirements change
- **Cleaner code**: The pipeline logic is more readable when normalization is abstracted

**Rule of thumb**: If you're about to write the same `gsub` or `split` pattern twice, extract it to a `def`.

## Selection & Ordering

### Multi-Condition Predicates

Chain sequential `select()` stages rather than trying to combine everything into one complex condition:

```jq
.[] |
select(.status == "active") |
select(.roles | map(normalize) | any(. == "admin" or . == "owner")) |
select(.email_domain as $ed | .blocked_domains | map(normalize) | all(. != $ed))
```

**Pattern**: Each `select()` handles one logical criterion. Use intermediate `as $var` bindings when a value is computed once and referenced multiple times.

### Mixed-Direction Sorting

jq's `sort_by` only sorts ascending. For multi-key sorting with mixed directions:

```jq
# Sort by email_domain ascending, then username descending
group_by(.email_domain) |
map(sort_by(.username) | reverse) |
add // []
```

**Mechanism**: `group_by` clusters records by the primary key (ascending). Within each group, `sort_by | reverse` gives descending order on the secondary key. `add // []` flattens the groups back into a single array, handling the empty case.

**Generalization**: For N-key sorting where key K is descending:
- Sort ascending by keys 1..K-1 using `group_by` chains or `sort_by([k1, k2, ...])`
- Within each group, apply `sort_by(kN) | reverse`
- Flatten with `add`

### Inclusion/Exclusion Logic

**Inclusion** (record must have at least one matching value):
```jq
select([$norm_roles[] | select(. == "admin" or . == "owner")] | length > 0)
```

**Exclusion** (record must NOT have a matching value):
```jq
select([$norm_blocked[] | select(. == $email_domain)] | length == 0)
```

**Pattern**: Build an array of matches, then check `length > 0` for inclusion or `length == 0` for exclusion.

## Field Derivation & Reshaping

### Binding Normalized Intermediates

Compute normalized values once with `as $var`, then reference them in the output construction:

```jq
(.roles | map(normalize) | unique) as $norm_roles |
(.email | split("@") | .[1] | ascii_downcase) as $email_domain |
{
  user_id: .id,
  email_domain: $email_domain,
  account_summary: {
    role_count: ($norm_roles | length),
    primary_role: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end),
    roles: $norm_roles
  }
}
```

**Pattern**: The output object can freely reference any `$var` binding from earlier in the pipeline. This avoids recomputing the same normalization multiple times.

### Nested Output Structures

Build nested objects by constructing the inner structure inline:

```jq
{
  account_summary: {
    role_count: ...,
    primary_role: ...,
    roles: ...
  }
}
```

**Generalization**: For deeper nesting, bind intermediate structures:
```jq
{
  role_count: ($norm_roles | length),
  primary_role: ...
} as $summary |
{
  user_id: .id,
  account_summary: $summary
}
```

### Combining Multiple Source Fields

String interpolation for combining fields:
```jq
contact: "\(.username) <\(.email)>"
```

Array construction for combining values:
```jq
combined: [.field1, .field2, .field3]
```

## Value Normalization

### Reusable Normalization Helpers

As shown in the Recommended Pattern section above, define `def` functions at the top of your filter for any normalization that appears more than once:

```jq
def normalize: gsub("^\\s+|\\s+$"; "") | ascii_downcase;
def extract_domain: split("@") | .[1] | ascii_downcase;
def extract_date: split("T") | .[0];
```

**Usage**: Apply with `map(normalize)` for arrays or just `normalize` for scalars.

**Common patterns** (extract to `def` if used more than once):
- **Trim + lowercase**: `gsub("^\\s+|\\s+$"; "") | ascii_downcase`
- **Extract domain**: `split("@") | .[1] | ascii_downcase`
- **Extract date**: `split("T") | .[0]`
- **Numeric coercion**: `tonumber` or `if type == "string" then tonumber else . end`
- **Boolean derivation**: `if . == "yes" or . == "true" then true else false end`

**When NOT to use `def`**: If a normalization appears only once, inline it. Don't over-abstract.

### Null/Blank Fallbacks

Handle missing or blank values with conditional logic. When you have a `normalize` function defined (see Recommended Pattern above), reuse it:

```jq
phone: (
  if .phone == null then "unknown"
  elif (.phone | normalize | length) == 0 then "unknown"
  else (.phone | normalize)
  end
)
```

**Pattern**: Check for `null` first, then check for blank (after trimming), then apply the normalization. Use a default value like `"unknown"`, `null`, or `0` as appropriate.

**Key insight**: The same `normalize` function used for roles and blocked domains can also handle phone trimming. This is exactly why `def` matters — one definition, multiple uses.

### Normalization Order

**Critical**: Normalize values BEFORE comparing them, and normalize again for output if needed:

```jq
# Normalize roles for comparison
(.roles | map(normalize) | unique) as $norm_roles |
# Check if any normalized role matches
select([$norm_roles[] | select(. == "admin")] | length > 0) |
# Use the already-normalized values in output
{
  roles: $norm_roles  # Already normalized
}
```

**Mechanism**: The `unique` function in jq both deduplicates AND sorts, so `map(normalize) | unique` gives you a sorted, deduplicated list of normalized values.

## Aggregation & Collection Operations

### Per-Record Collection Operations

**Deduplication + sorting**: `unique` does both in one step
```jq
.roles | map(normalize) | unique
```

**Counting**: `length` on arrays
```jq
role_count: ($norm_roles | length)
```

**First/last element**: Index access after sorting
```jq
primary_role: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end)
```

### Cross-Record Aggregation

**Grouping**: `group_by` clusters records by a key
```jq
group_by(.email_domain)
```

**Aggregating over groups**: Map over groups and compute summaries
```jq
group_by(.department) |
map({
  department: .[0].department,
  count: length,
  avg_salary: (map(.salary) | add / length)
})
```

**⚠️ Empty-group safety for numeric aggregation**: `add` on an empty array returns `null`, not `0`. When a group might be empty or when summing a possibly-empty field list, guard with `// 0` or use `reduce`:

```jq
# Safe sum — returns 0 for empty groups
map(.salary) | add // 0

# Safe sum via reduce — always starts from accumulator
reduce .[] as $r (0; . + $r.salary)

# Safe average — guard against division by zero too
(if length > 0 then (map(.salary) | add / length) else 0 end)
```

**Why this matters**: `null` propagates silently through arithmetic (`null + 1` is `null` in jq), producing wrong totals without error. Always use `add // 0` or `reduce` for numeric cross-record aggregation.

**Flattening**: `add` concatenates arrays
```jq
[.[] | .tags] | add  # Flattens array of arrays into single array
```

**Deduplication across records**: `unique` on the flattened array
```jq
[.[] | .roles[]] | unique
```

## YAML/Config Serialization

### The Escape Hell Problem

When saving jq filters to YAML, double-quoted strings interpret escape sequences:
- `\\s` becomes `\s` (YAML interprets `\\` as `\`)
- Double quotes inside the filter need `\"` escaping
- `$variable` names may be interpreted by the shell

### Solution: Block Scalars

Use YAML block scalars (`|`) for the filter value:

```yaml
filter: |
  [
    .[] |
    select(.status == "active") |
    (.roles | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase) | unique) as $norm_roles |
    ...
  ]
args:
  - "--indent 2"
```

**Mechanism**: Block scalars take content literally — no escape processing. The `\\s` in the filter stays as `\\s`, which jq interprets as `\s` (regex whitespace).

### Round-Trip Verification

**Always verify** that the reconstructed command produces identical output:

```bash
# Save reference output
jq --indent 2 -f filter.jq input.json > reference.json

# Reconstruct from YAML
jq $(yq -r '.args[]' config.yaml) "$(yq -r '.filter' config.yaml)" input.json > output.json

# Compare
diff reference.json output.json && echo "MATCH" || echo "MISMATCH"
```

**Why**: This catches YAML escaping issues, shell variable expansion, and argument parsing problems before the evaluator does.

## Debugging Checklist

1. **No records in output?**
   - Check each `select()` stage individually
   - Verify normalization is applied before comparison
   - Check for null/missing fields

2. **Wrong records included?**
   - Verify exclusion logic (`length == 0` not `length > 0`)
   - Check normalization consistency (same normalization for both sides of comparison)

3. **Wrong sort order?**
   - Verify `group_by` key matches primary sort key
   - Check `reverse` placement (after `sort_by`, before `add`)
   - Test with small dataset to inspect ordering

4. **YAML reconstruction fails?**
   - Use block scalar (`|`) for filter
   - Verify `args` array format: each item is a complete argument including flag
   - Test round-trip with diff

5. **Nested output structure wrong?**
   - Check `$var` bindings are in scope
   - Verify object construction syntax
   - Test with minimal example first

## Generalization Strategy

When adapting to a new variant:

1. **Identify the four stages**: What are the selection criteria? What needs normalization? What's the output shape? What aggregation is needed?

2. **Map to patterns**: Each stage maps to one of the patterns above. The specific fields and logic vary, but the structural patterns are stable.

3. **Test incrementally**: Build and test each stage separately before combining.

4. **Verify serialization**: Always do the round-trip check when saving to YAML/config.

5. **Distinguish invariants from variation**:
   - **Invariant**: Use jq, produce JSON, handle arrays of records, serialize to config
   - **Varies**: Specific filter criteria, field names, normalization rules, sort keys, aggregation logic
