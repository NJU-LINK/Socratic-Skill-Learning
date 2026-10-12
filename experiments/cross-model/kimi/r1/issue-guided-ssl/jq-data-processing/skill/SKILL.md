---
name: jq-data-processing
description: Transform JSON data using jq with proper handling of selection predicates, field derivation, value normalization, and aggregation operations.
---

# jq-data-processing Skill

This skill provides a systematic approach to building jq filters for JSON data transformation tasks involving record selection, field reshaping, value normalization, and aggregation.

## Derivation Workflow

### 1. Input Analysis
- Identify input record structure and field types
- Locate fields required for selection predicates
- Locate fields requiring transformation/derivation
- Identify optional/nullable fields (use `?` and `//` for safety)

### 2. Axes Classification
Map task requirements onto the four transformation axes:

**Selection & Ordering (Axis 1)**
- Define inclusion/exclusion predicates
- Classify as existential (any), universal (all), or membership (IN/contains)
- Determine sort keys and direction for each

**Field Derivation & Reshaping (Axis 2)**
- Map input fields to output fields
- Identify nested object construction needs
- Plan field renaming and structural changes

**Value Normalization (Axis 3)**
- Define trim, case conversion, and cleanup operations
- Plan default value substitutions
- Identify string parsing/extraction patterns

**Aggregation & Collection (Axis 4)**
- Identify deduplication requirements (unique)
- Plan grouping operations (group_by)
- Determine collection-level summaries needed

### 3. Pipeline Assembly
Canonical pipeline structure:

```jq
def trim: gsub("^\\s+|\\s+$"; "");
def norm: trim | ascii_downcase;

def predicate1: ...;
def predicate2: ...;

[.[] |
 select(.status == "active") |
 select(predicate1) |
 (computed_value) as $var |
 select(predicate2) |
 {
   output_field: .input_field,
   derived: ($var | transformation)
 }] |
 sort_operation
```

### 4. Validation Checklist
- Output is a JSON array: `type=="array"`
- No duplicate records: `length == (map(.key)|unique|length)`
- Spot-check: verify one included record has correct fields
- Spot-check: verify one excluded record is properly filtered out
- Verify sort order with sample comparisons

## Critical Correctness Rules

### Single-Boolean Predicates Rule
**Never** let a generator flow into `select`, `if`, or boolean operators directly. Generators multiply the input, causing duplicate records.

**Wrong (duplicates rows):**
```jq
select(.roles[] | . == "admin" or . == "owner")
```

**Right (single boolean):**
```jq
select(any(.roles[]; . == "admin" or . == "owner"))
```

**Pattern:**
- Existential (at least one satisfies): `any(generator; condition)`
- Universal (all satisfy): `all(generator; condition)`
- Membership: `value | IN(set)` or `array | contains([value])`

### Mixed-Direction Sort
jq's `sort_by` does not support per-key direction. For mixed asc/desc sorting:

```jq
# Sort by domain asc, then username desc
group_by(.email_domain) | map(sort_by(.username) | reverse) | add
```

Alternative using negated codepoints:
```jq
sort_by(.email_domain, (.username | explode | map(-.)))
```

### Optional Field Handling
```jq
# Safe access with null default
(.optional_field // "") | process

# Safe array iteration
.array_field[]?
```

### Normalization Helpers
```jq
def trim: gsub("^\\s+|\\s+$"; "");
def norm: trim | ascii_downcase;
def ymd: split("T")[0];  # ISO 8601 to YYYY-MM-DD
```

### Collection Operations
- `unique`: Sort and remove duplicates
- `group_by(key)`: Group records by key value
- `flatten`: Flatten nested arrays
- `add`: Sum numbers or concatenate arrays

## Artifact Contract

The task requires three artifacts:
1. **Output file**: JSON array with specified structure
2. **cmd.sh**: Exact jq command with redirection
3. **jq_args.yaml**: Filter and args for command reconstruction

### jq_args.yaml Schema

```yaml
filter: string    # Complete jq filter expression
args: [string]    # List of jq CLI arguments
```

**Critical per-item shape rule**: Each item in `args` must be one complete argument, flag and value together in a single string. The reconstruction uses unquoted `$(yq -r '.args[]')`, which word-splits each item.

**RIGHT:**
```yaml
args:
  - "--indent 2"
  - "--raw-input"
```

**WRONG (counterexample - '2' fails validation):**
```yaml
args:
  - "--indent"
  - "2"
```

**Structural validator:**
```bash
yq -j . jq_args.yaml | jq -e '
  (keys | sort == ["args","filter"]) and
  (.filter | type == "string") and
  (.args | type == "array") and
  (.args | all(type == "string" and startswith("-")))'
```

Note: `args: []` is valid when jq defaults suffice (jq's default indent is 2 spaces).

### cmd.sh Shape Rules

The cmd.sh must be a single self-contained command with specific structural requirements:

**Shape requirements:**
- First token must be `jq` (starts with `jq `)
- Must use absolute paths exactly as the task declares them
- Must include explicit output redirection (`>`)
- Filter text must be identical to jq_args.yaml's filter

**RIGHT:**
```bash
jq --indent 2 'def trim: ...; [...]' /app/users.json > /app/verified_admin_contacts.json
```

**WRONG (relative paths - fails structural validation):**
```bash
jq --indent 2 'def trim: ...; [...]' users.json > verified_admin_contacts.json
```

**Structural validator:**
```bash
grep -qE '^jq ' /app/cmd.sh && \
grep -qF '/app/users.json' /app/cmd.sh && \
grep -qF '/app/verified_admin_contacts.json' /app/cmd.sh && \
grep -qE '> /app/[^ ]+$' /app/cmd.sh
echo "cmd.sh structure valid"
```

**Note on asymmetry:** cmd.sh includes absolute input/output paths (it's the full command), while jq_args.yaml intentionally omits them (the reconstruction template supplies them). Same filter text in both, different path treatment.

### Functional Verification

Verify the reconstructed command produces identical output:
```bash
jq $(yq -r '.args[]' jq_args.yaml) "$(yq -r '.filter' jq_args.yaml)" /app/users.json > /app/verified_admin_contacts.json
```
