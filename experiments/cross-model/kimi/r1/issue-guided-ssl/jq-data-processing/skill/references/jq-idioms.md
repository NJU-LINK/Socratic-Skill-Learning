# jq Idioms Reference

## Boolean Predicate Patterns

### Existential Quantification
Check if at least one element satisfies a condition.

```jq
# Any role is "admin" or "owner"
any(.roles[]; . == "admin" or . == "owner")

# With normalization (requires trim def)
def trim: gsub("^\\s+|\\s+$"; "");
any(.roles[]; ascii_downcase | trim == "admin")
```

### Universal Quantification
Check if all elements satisfy a condition.

```jq
# All roles are privileged
all(.roles[]; . == "admin" or . == "owner")
```

### Membership Testing
```jq
# Check if value is in set (comma-separated stream, not semicolons)
"admin" | IN("admin", "owner", "user")

# Check if array contains value (normalized)
[.blocked[] | norm] | contains([$email_domain])

# Alternative membership tests:
any(.blocked[]; norm == $email_domain)    # stream form
(.blocked | map(norm) | index($email_domain)) != null  # index form
```

**Caveat:** `contains` is *deep containment*, not equality-membership. On strings it's a substring test (`"foobar" | contains("bar")` → true). On objects it's recursive key-subset. Safe for scalars inside arrays as `array | contains([$scalar])`, but dangerous for general membership testing.

**Critical:** Never use bare generators in `select`:
```jq
# WRONG: duplicates rows for multiple matches
select(.roles[] | . == "admin")

# RIGHT: single boolean result
select(any(.roles[]; . == "admin"))
```

## String Normalization

```jq
def trim: gsub("^\\s+|\\s+$"; "");
def norm: trim | ascii_downcase;
def extract_domain: split("@")[1] | norm;
```

## Date Handling

```jq
# ISO 8601 to YYYY-MM-DD (tolerant of suffixes)
def ymd: split("T")[0];

# Using strptime (stricter)
(.date | strptime("%Y-%m-%dT%H:%M:%SZ") | strftime("%Y-%m-%d"))
```

## Mixed-Direction Sorting

```jq
# email_domain ascending, username descending
group_by(.email_domain) | map(sort_by(.username) | reverse) | add // []

# Alternative: negated codepoints
sort_by(.email_domain, (.username | explode | map(-.)))
```

## Optional/Null Field Handling

```jq
# Default for null/missing
(.phone // "") | process

# Trim then default
(.phone // "" | trim | if . == "" then "unknown" else . end)

# Safe array access
.array_field[]?  # empty if null or missing
```

## Collection Transformations

```jq
# Normalize, deduplicate, sort (unique does all three)
[.roles[] | norm] | unique

# Group then aggregate
group_by(.category) | map({cat: .[0].category, count: length})

# Flatten nested structure
[.items[].subitems[]] | unique
```

## Pipeline Stage Patterns

### Selection Before Transformation
```jq
[.[] |
 select(.status == "active") |
 select(any(.roles[]; . == "admin")) |
 {transformed}]
```

### Binding Derived Values
```jq
(.email | extract_domain) as $domain |
select([.blocked[] | norm] | contains([$domain]) | not)
```

### Nested Object Construction
```jq
{
  user_id: .id,
  contact: "\(.name) <\(.email)>",
  summary: {
    count: (.items | length),
    first: (.items[0] // null)
  }
}
```

## Validation Checks

```jq
# Output is array
jq -e 'type == "array"' output.json

# No duplicate IDs
jq -e 'length == (map(.id) | unique | length)' output.json

# Check specific record exists
jq -e 'map(.user_id) | contains([123])' output.json
```
