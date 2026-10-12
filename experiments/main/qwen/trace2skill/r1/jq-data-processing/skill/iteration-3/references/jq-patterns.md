# jq Processing Patterns

Proven patterns for common data processing tasks in jq.

## Sorting with Mixed Directions
jq's `sort_by` is stable. To sort by multiple keys with different directions (e.g., ascending primary, descending secondary), chain sorts in reverse priority order:
```jq
sort_by(.secondary_key) | reverse | sort_by(.primary_key)
```
This sorts by the secondary key, reverses it (making it descending), then stably sorts by the primary key (ascending).

## String Normalization and Deduplication
When deduplicating or comparing string arrays that require normalization (trimming, lowercasing), pipe through normalization then use `unique`. The `unique` builtin sorts and deduplicates in one step:
```jq
.roles | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase) | unique
```

## Exclusion Checks with Normalized Index Lookup
When filtering records based on whether a derived value appears in an exclusion list, normalize both sides and use `index()` for membership testing (`== null` means not found):
```jq
(.email | split("@") | last | ascii_downcase) as $domain |
(.blocked_domains | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase)) as $blocked |
select(($blocked | index($domain)) == null)
```

## YAML/Bash Filter Integration
Store complex jq filters containing double quotes and backslashes in a YAML literal block scalar (`filter: |`). Reconstruct with `yq -r '.filter'` inside bash double-quoted command substitution.
```yaml
filter: |
  [.[] | select(.status == "active") | ...]
args:
  - "--indent 2"
```
```bash
jq $(yq -r '.args[]' file.yaml) "$(yq -r '.filter' file.yaml)" input.json > output.json
```