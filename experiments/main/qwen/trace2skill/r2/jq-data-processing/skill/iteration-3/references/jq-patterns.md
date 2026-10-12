# Proven jq Patterns

## Table of Contents
- [Mixed-Direction Multi-Key Sorting](#mixed-direction-multi-key-sorting)
- [String Normalization and Null-Safety](#string-normalization-and-null-safety)
- [Safe Serialization of Complex Filters to YAML](#safe-serialization-of-complex-filters-to-yaml)

## Mixed-Direction Multi-Key Sorting
When sorting an array of objects by multiple keys with different sort directions (e.g., primary ascending, secondary descending), exploit the stability of jq's `sort_by`. 
First sort by the secondary key in the desired direction (using `reverse` for descending), then sort by the primary key ascending. The stable sort preserves the secondary ordering within primary groups.
```jq
sort_by(.secondary_key) | reverse | sort_by(.primary_key)
```

## String Normalization and Null-Safety
When normalizing strings that may contain erratic whitespace, mixed casing, or be null/missing, chain null-coalescing, regex trimming, and case conversion. 
Use `// ""` to handle nulls safely, `gsub` to trim whitespace, and `ascii_downcase` for case normalization. This prevents type errors on null values.
*Note:* Use double-escaped backslashes (`\\s`) inside jq string literals so the regex engine receives `\s`.
```jq
(.field // "") | gsub("^\\s+|\\s+$"; "") | ascii_downcase
```

## Safe Serialization of Complex Filters to YAML
When saving a complex, multi-line jq filter (with quotes, interpolations, regex backslashes) into a YAML file for later shell reconstruction, avoid manual shell escaping or heredocs which mangle backslashes. 

**Option 1: YAML Literal Block Scalar**
Use a YAML literal block scalar (`|`) to preserve backslashes and quotes exactly. The `\\s` in the `.jq` source becomes `\s` in the YAML block, which `yq` outputs literally, and `jq` parses as the regex `\s`.
```yaml
filter: |
  [.[] | select(.status == "active") | ... gsub("^\\s+|\\s+$"; "") ...]
args: []
```

**Option 2: Python Serialization**
Alternatively, use a brief Python script with `yaml.dump()` to safely serialize the filter string and arguments, ensuring exact round-trip fidelity when read back by `yq`.
```python
import yaml
filter_text = open('filter.jq').read().rstrip('\n')
data = {'filter': filter_text, 'args': ['--indent 2']}
with open('jq_args.yaml', 'w') as f:
    yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
```
