# jq Patterns Cheat Sheet

## String Operations

```jq
# Trim whitespace (no built-in trim in jq)
gsub("^\\s+|\\s+$"; "")

# Lowercase
ascii_downcase

# Uppercase
ascii_upcase

# String interpolation
"\(.field1) separator \(.field2)"

# Split string
"foo@bar.com" | split("@")        # ["foo", "bar.com"]
"foo@bar.com" | split("@")[1]     # "bar.com"

# Regex match/capture
"2026-03-16T05:01:40Z" | capture("^(?<date>\\d{4}-\\d{2}-\\d{2})") | .date

# Test pattern
"hello" | test("^h")              # true

# Replace
"foo bar" | gsub(" "; "_")        # "foo_bar"

# Substring
"2026-03-16T05:01:40Z" | .[0:10]  # "2026-03-16"
```

## Null Safety

```jq
# Default value for null
.field // "default"

# Null-coalesce before string ops
((.phone // "") | gsub("^\\s+|\\s+$"; ""))

# Null-coalesce before array ops
((.items // []) | map(.name))

# Check if field exists
has("field")

# Optional field access (returns null if missing, no error)
.field?
```

## Array Operations

```jq
# Unique (dedup + sort ascending)
[1, 2, 1, 3] | unique              # [1, 2, 3]

# Length
[1, 2, 3] | length                  # 3

# First/last
[1, 2, 3] | .[0]                   # 1
[1, 2, 3] | .[-1]                  # 3

# Flatten
[[1, 2], [3, 4]] | add             # [1, 2, 3, 4]
[[1, [2]], [3]] | flatten          # [1, 2, 3]

# Map
[1, 2, 3] | map(. * 2)             # [2, 4, 6]

# Select from array
[1, 2, 3, 4] | [.[] | select(. > 2)]  # [3, 4]

# Any/all
[1, 2, 3] | any(. > 2)            # true
[1, 2, 3] | all(. > 0)            # true

# Index/contains
["a", "b", "c"] | index("b")      # 1
["a", "b", "c"] | contains(["b"]) # true

# IN (jq 1.6+)
"admin" | IN("admin", "owner")    # true

# Sort by
[{n: "b"}, {n: "a"}] | sort_by(.n)  # [{n:"a"},{n:"b"}]

# Group by
[{g:1,v:"a"},{g:2,v:"b"},{g:1,v:"c"}] | group_by(.g)
# [[{g:1,v:"a"},{g:1,v:"c"}],[{g:2,v:"b"}]]

# Reverse
[1, 2, 3] | reverse                # [3, 2, 1]
```

## Object Operations

```jq
# Rename fields
{new_name: .old_name}

# Computed fields
{total: (.price * .quantity)}

# Nested objects
{summary: {count: (.items | length), names: [.items[].name]}}

# Merge objects
{a: 1} + {b: 2}                   # {a:1, b:2}

# Dynamic keys
{(.type): .value}

# Select keys
{a:1, b:2, c:3} | with_entries(select(.key != "b"))  # {a:1, c:3}
```

## Variable Binding

```jq
# Bind computed value for reuse
(.email | split("@")[1]) as $domain |
{domain: $domain, is_free: ($domain | IN("gmail.com", "yahoo.com"))}

# Multiple bindings
(.x + 1) as $a |
(.y * 2) as $b |
{sum: ($a + $b)}
```

## Sorting Patterns

```jq
# Single key ascending
sort_by(.name)

# Multiple keys ascending
sort_by([.last_name, .first_name])

# Mixed direction (group-then-reverse)
sort_by(.group) |
group_by(.group) |
map(sort_by(.name) | reverse) |
add // []

# Mixed direction (character inversion — strings only)
sort_by([.group, (.name | explode | map(255 - .) | implode)])
```

## Aggregation Patterns

```jq
# Count by group
group_by(.category) |
map({category: .[0].category, count: length})

# Sum by group
group_by(.department) |
map({
  department: .[0].department,
  total_salary: ([.[].salary] | add)
})

# Collect unique values across records
[.[].role] | unique

# Flatten nested arrays
[.[].tags[]] | unique
```

## Pipeline Patterns

```jq
# Filter → transform → sort → output
[.[] |
  select(.status == "active") |
  (.name | ascii_downcase) as $name |
  {name: $name, score: .score}
] | sort_by(.name)

# Conditional transformation
if .type == "date" then .[0:10]
elif .type == "number" then . | tonumber
else . end

# Reduce for accumulation
reduce .[] as $item (
  {};
  .[$item.category] += 1
)
```
