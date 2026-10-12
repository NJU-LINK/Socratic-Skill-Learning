# jq Pattern Library

Reusable jq snippets for common data transformation tasks.

## Value Normalization

### Trim whitespace and lowercase
```jq
gsub("^\\s+|\\s+$";"") | ascii_downcase
```
Use for: role names, enum values, domain names, any case-insensitive comparison.

### Extract email domain
```jq
.email | split("@")[1] | ascii_downcase
```

### Extract date from ISO 8601
```jq
.timestamp | split("T")[0]
```
Returns: YYYY-MM-DD

### Normalize array elements
```jq
.roles | map(gsub("^\\s+|\\s+$";"") | ascii_downcase)
```

### Null-safe array access
```jq
.blocked_domains // []
```

## Filtering

### Check if array contains value
```jq
array | index(value)  # returns index or null
array | index(value) | not  # returns true if NOT found
```

### Check if any element matches predicate
```jq
array | any(. == "value")
array | any(. == "admin" or . == "owner")
```

### Multi-condition select
```jq
select(.status == "active" and $has_priv and ($blocked | index($domain) | not))
```

### Pattern: normalize then filter
```jq
(.field | normalize) as $norm |
select($norm == "value")
```

## Aggregation

### Deduplicate and sort
```jq
array | unique
```
Returns sorted unique values.

### Count elements
```jq
array | length
```

### First element with null guard
```jq
if (array | length) > 0 then array[0] else null end
```

### Group by field
```jq
group_by(.field)
```
Returns: array of arrays grouped by field value.

### Flatten grouped arrays
```jq
group_by(.field) | map(...) | add
```

## Sorting

### Single key ascending
```jq
sort_by(.field)
```

### Multiple keys ascending
```jq
sort_by(.field1, .field2)
# or
sort_by([.field1, .field2])
```

### Mixed direction (asc field1, desc field2)
```jq
group_by(.field1) | map(sort_by(.field2) | reverse) | add // []
```
Note: `add // []` guards against empty input (since `add` on `[]` returns `null`).

## Field Transformation

### Rename field
```jq
{ new_name: .old_name }
```

### Combine fields
```jq
{ contact: "\(.username) <\(.email)>" }
```

### Nested output object
```jq
{
  summary: {
    count: (array | length),
    first: (if (array | length) > 0 then array[0] else null end)
  }
}
```

## Conditional Values

### Null/blank with fallback
```jq
if .field == null or (.field | gsub("^\\s+|\\s+$";"") | length) == 0
then "default"
else .field
end
```

### Simplified null coalescing
```jq
.field // "default"
```
Note: Only handles null, not empty strings.

## Common Compositions

### Normalize, deduplicate, check membership
```jq
(.roles | map(gsub("^\\s+|\\s+$";"") | ascii_downcase) | unique) as $norm |
($norm | any(. == "admin")) as $has_admin |
select($has_admin)
```

### Extract, normalize, compare against list
```jq
(.email | split("@")[1] | ascii_downcase) as $domain |
(.blocked | map(gsub("^\\s+|\\s+$";"") | ascii_downcase)) as $blocked |
select($blocked | index($domain) | not)
```

### Build output with aggregation
```jq
{
  user_id: .id,
  roles: $norm_roles,
  summary: {
    count: ($norm_roles | length),
    primary: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end)
  }
}
```

### Complete pipeline structure
```jq
[
  .[] |
  # Normalize
  (.field | normalize) as $norm |
  
  # Compute predicates
  ($norm | check) as $predicate |
  
  # Filter
  select($predicate) |
  
  # Transform
  {
    output_field: .input_field,
    derived: $norm
  }
] |
# Sort
sort_by(.field) |
# or for mixed direction:
group_by(.field1) | map(sort_by(.field2) | reverse) | add
```

## Parameterization

### Pass string parameter
```bash
jq --arg status "active" '.[] | select(.status == $status)' input.json
```

### Pass JSON value (array, number, boolean)
```bash
jq --argjson priv_roles '["admin","owner"]' '.[] | select(.roles | any(. as $r | $priv_roles | index($r)))' input.json
```

### Parameterized filter pattern
```jq
.[] |
select(.status == $status) |
select(.roles | any(. as $r | $priv_roles | index($r)))
```

### YAML args with parameters
```yaml
args:
  - "--indent 2"
  - "--arg status active"
  - "--argjson priv_roles [\"admin\",\"owner\"]"
```
Note: Each item must start with `-` (flag). Shell word-splitting separates flag+value into distinct arguments for jq.

## Edge Cases

### Empty array handling
```jq
# unique on [] returns []
# .[0] on [] returns null
# length on [] returns 0
# add on [] returns null (not [])!

# Guard before accessing first element
if (array | length) > 0 then array[0] else null end

# Guard add on potentially empty result
group_by(.field) | map(...) | add // []
```

### Missing fields
```jq
.field // default_value
.field // []  # for arrays
```

### Null propagation
```jq
# Operations on null return null
null | length  # returns 0
null | .field  # returns null
null | split("x")  # error!

# Guard with // operator
.field // [] | length
```

## Performance Notes

- Use `as` bindings to avoid recomputing normalized values
- `unique` is O(n log n) due to sorting
- `group_by` requires sorted input for efficiency
- `index()` is O(n) for arrays
- For large datasets, consider `INDEX()` or `GROUP_BY()` functions
