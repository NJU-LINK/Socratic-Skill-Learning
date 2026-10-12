# jq Pattern Reference for Data Processing

## String Operations

### Trim Whitespace
```jq
# Trim leading and trailing whitespace
gsub("^\\s+|\\s+$"; "")

# Trim only leading
gsub("^\\s+"; "")

# Trim only trailing
gsub("\\s+$"; "")
```

### Case Normalization
```jq
# Lowercase
ascii_downcase

# Uppercase
ascii_upcase
```

### Combined: Trim + Lowercase (the universal normalize)
```jq
def normalize: gsub("^\\s+|\\s+$"; "") | ascii_downcase;
```

### String Splitting
```jq
# Split on delimiter
split("@")          # ["user", "domain.com"]
split("T")          # ["2026-01-01", "12:00:00Z"]

# Extract part after split
split("@")[1]       # "domain.com"
split("T")[0]       # "2026-01-01"
```

### String Slicing
```jq
.[0:10]             # First 10 characters (ISO date extraction)
.[5:]               # From index 5 to end
.[-3:]              # Last 3 characters
```

### String Interpolation
```jq
"\(.username) <\(.email)>"    # "john <john@example.com>"
"Count: \(.items | length)"   # "Count: 5"
```

## Null Safety

### Default Values
```jq
.field // "default"           # Use "default" if .field is null or false
.field // []                  # Use empty array if null
.field // 0                   # Use 0 if null
.field // ""                  # Use empty string if null
```

### Conditional Null Handling
```jq
# Different behavior for null vs empty string
if .field == null then "missing"
elif .field == "" then "blank"
else .field
end
```

## Array Operations

### Mapping
```jq
map(.field)                    # Extract field from each element
map(normalize)                 # Apply function to each element
map(. + "_suffix")            # Transform each element
```

### Filtering
```jq
map(select(. > 5))            # Keep elements > 5
[.[] | select(.active)]       # Same, using .[] iteration
```

### Deduplication and Sorting
```jq
unique                         # Deduplicate AND sort ascending
unique_by(.id)                # Deduplicate by key function
sort                           # Sort array of scalars
sort_by(.name)                # Sort by key function
sort_by(.name) | reverse      # Sort descending
```

### Flattening
```jq
flatten                        # Flatten nested arrays completely
flatten(1)                     # Flatten one level only
[.[] | .items[]]              # Extract all items from nested arrays
```

### Aggregation
```jq
length                         # Count elements
add                            # Sum numbers or concatenate strings
min / max                      # Minimum / maximum
first / last                   # First / last element (.[0] / .[-1])
any(condition)                 # True if any element matches
all(condition)                 # True if all elements match
```

## Object Operations

### Field Access
```jq
.field                         # Direct access
.["field-name"]               # Access with special characters
.nested.deep.field            # Deep access
.field1, .field2              # Multiple fields (produces multiple outputs)
```

### Object Construction
```jq
{
  new_name: .old_name,
  computed: (.a + .b),
  nested: { inner: .value }
}
```

### Field Modification
```jq
.field |= normalize           # Modify field in place
.field = "new_value"          # Set field to literal
del(.unwanted)                # Remove field
+ { new_field: "value" }     # Add/merge fields
```

## Variable Binding

### Single Value
```jq
.expression as $var |         # Bind result to $var
... use $var ...
```

### Multiple Values
```jq
(.a | normalize) as $norm_a |
(.b | normalize) as $norm_b |
{ result: ($norm_a + $norm_b) }
```

## Conditional Logic

### Select (Filter)
```jq
select(.status == "active")              # Keep matching records
select(.roles | any(. == "admin"))       # Complex condition
select(.blocked | index(.domain) | not)  # Negated membership
```

### If-Then-Else
```jq
if condition then value1 else value2 end
if .field == null then "unknown" else .field end
```

### Alternative Operator
```jq
.field // "default"          # If .field is null/false, use "default"
.field1 // .field2 // "none" # Chain alternatives
```

## Cross-Field Comparisons

### Membership Check
```jq
# Check if value is in array
$array | index($value)        # Returns index or null
$array | index($value) | not  # Negated: true if NOT in array
$value | IN($array[])         # Alternative syntax (jq 1.6+)
```

### Normalized Comparison
```jq
# Normalize both sides before comparing
(.email | split("@")[1] | ascii_downcase) as $domain |
(.blocked_domains // [] | map(normalize)) as $blocked |
select($blocked | index($domain) | not)
```

## Sorting Patterns

### Single Key Ascending
```jq
sort_by(.field)
```

### Single Key Descending
```jq
sort_by(.field) | reverse
```

### Multi-Key: Primary Ascending, Secondary Descending
```jq
# Sort secondary key first (descending), then primary key (ascending)
sort_by(.secondary) | reverse |
sort_by(.primary)
```

### Multi-Key: Both Ascending
```jq
sort_by(.primary, .secondary)
# or
sort_by([.primary, .secondary])
```

### Multi-Key: Both Descending
```jq
sort_by([.primary, .secondary]) | reverse
```

### Multi-Key: Complex Directions
```jq
# Primary ascending, secondary descending, tertiary ascending
sort_by(.tertiary) |
sort_by(.secondary) | reverse |
sort_by(.primary)
```

## Grouping and Aggregation

### Group By Key
```jq
group_by(.category)
# Returns array of arrays, each group sharing the same .category value
```

### Per-Group Aggregation
```jq
group_by(.category) |
map({
  category: .[0].category,
  count: length,
  items: [.[] | .name]
})
```

### Cross-Record Deduplication
```jq
[.[] | .field] | unique
# Collect all values, then deduplicate
```

## Complete Pipeline Template

```jq
def normalize: gsub("^\\s+|\\s+$"; "") | ascii_downcase;

[
  .[] |
  
  # Stage 1: Compute normalized intermediate values
  (.email | split("@")[1] | ascii_downcase) as $domain |
  (.blocked_list // [] | map(normalize)) as $blocked |
  (.roles // [] | map(normalize) | unique) as $norm_roles |
  
  # Stage 2: Filter records
  select(.status == "active") |
  select($blocked | index($domain) | not) |
  select($norm_roles | any(. == "admin" or . == "owner")) |
  
  # Stage 3: Reshape output
  (.phone // "" | normalize) as $phone |
  {
    id: .user_id,
    name: .username,
    domain: $domain,
    contact: "\(.username) <\(.email)>",
    phone: (if $phone == "" then "unknown" else $phone end),
    date: (.timestamp[0:10]),
    summary: {
      count: ($norm_roles | length),
      primary: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end),
      roles: $norm_roles
    }
  }
]

# Stage 4: Sort
| sort_by(.secondary_key) | reverse
| sort_by(.primary_key)
```

## Debugging Tips

### Inspect Intermediate Values
```jq
# Print value and pass through
.field | debug | .

# Print label and value
. as $x | "Value: \($x)" | debug | $x
```

### Check Array Contents
```jq
# Show first few elements
.[:3]

# Show structure
.[:1] | keys

# Count elements
length
```

### Validate Transformations
```jq
# Check if transformation produced expected structure
.[:1] | .[0] | keys
```
