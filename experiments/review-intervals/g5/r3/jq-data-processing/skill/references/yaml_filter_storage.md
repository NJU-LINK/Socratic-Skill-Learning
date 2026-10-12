# YAML Filter Storage for jq

## Problem

Complex jq filters contain pipes (`|`), quotes, dots, brackets, and backslashes that interact badly with shell quoting and YAML parsing. Storing them in a YAML file and reconstructing the command at runtime avoids quoting hell.

## Block Scalar Styles

### `|-` (strip trailing newline) — PREFERRED

```yaml
filter: |-
  [.[] | select(.status == "active") | {name: .username}]
  | sort_by(.name)
```

The `|-` indicator strips the trailing newline. The filter string ends exactly at the last character of content.

### `|` (keep trailing newline)

```yaml
filter: |
  [.[] | select(.status == "active")]
```

Adds a trailing `\n` to the string. Usually harmless for jq (jq ignores trailing whitespace in filters), but can cause issues with exact-match tests.

### `>` (folded) — AVOID for jq

Folds newlines into spaces, which breaks multi-line jq expressions.

## Complete YAML Structure

```yaml
filter: |-
  [.[] |
    select(.status == "active") |
    (.roles | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase) | unique) as $norm_roles |
    select($norm_roles | any(. == "admin" or . == "owner")) |
    {user_id: .id, roles: $norm_roles}
  ] | sort_by(.user_id)
args:
  - "--indent 2"
```

### Key rules:
- `filter`: a single string containing the jq expression
- `args`: a list of strings, where **each item is one complete jq argument including both a flag and its value** as a single string — every item must start with `-`
- Use `|-` for the filter to avoid trailing newline
- Indentation in the block scalar is relative — the YAML parser strips the common leading whitespace

## Reconstruction

```bash
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/users.json > /app/output.json
```

### Why `$(yq -r '.args[]')` unquoted?
Each arg is a separate list item, so word splitting produces separate arguments. For example, `"--indent 2"` becomes two args to jq: `--indent` and `2`. This is correct — jq expects `--indent` followed by the value `2` as separate command-line arguments.

### Why `"$(yq -r '.filter')"` quoted?
The filter is a single argument containing spaces and special characters. Quoting preserves it as one argument.

## Verification

Always verify the YAML round-trips correctly before running:

```bash
# Check filter reads back correctly
yq -r '.filter' /app/jq_args.yaml | head -5

# Check args expand correctly
yq -r '.args[]' /app/jq_args.yaml

# Dry-run: echo the reconstructed command
echo jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/users.json
```

## Escaping Gotchas

- In YAML block scalars, backslashes are literal — `\\s+` in the block scalar becomes `\\s+` in the string, which jq interprets as `\s+` (regex whitespace). This is correct.
- Double quotes inside the block scalar are literal — no escaping needed.
- The `$var` syntax for jq variables passes through YAML unchanged.

## When to Also Write cmd.sh

The task may require a `cmd.sh` containing the exact command with output redirection. Write the literal direct command (not the yq-based reconstruction):

```bash
#!/bin/bash
jq --indent 2 '[.[] | select(...) | {...}] | sort_by(...)' /app/input.json > /app/output.json
```

This is independent of the YAML file — both should produce identical output.
