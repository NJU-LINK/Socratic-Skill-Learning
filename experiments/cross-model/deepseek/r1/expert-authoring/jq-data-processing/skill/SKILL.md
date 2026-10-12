---
name: jq-data-processing
description: >
  General workflow for jq-based JSON-to-JSON transformation tasks: inventory the input,
  normalize-then-filter-then-shape ordering, mixed-direction multi-key sorting, per-record
  plus cross-record aggregation, and packaging deliverables as jq_args.yaml + cmd.sh with
  byte-level self-verification of the produced report.
---

# jq data-processing tasks

## What is fixed across this task family (invariants)

Verified against the anchor case (v01) on a jq 1.6 + yq environment; treat as the default
interface, but re-check the instruction text on every variant — nothing here overrides it.

- One or more JSON files are given under `/app` (paths named in the instruction).
- The deliverable is one JSON report written to an `/app/*.json` path, produced **with jq
  only**. Python/Ruby/etc. must not generate the report.
- Two packaging artifacts are always produced (exact keys, nothing else at top level):
  - `/app/jq_args.yaml` with exactly two keys:
    - `filter`: one string containing the jq filter expression.
    - `args`: a list of strings of the form the task describes as "one complete jq argument
      including both a flag and its value when applicable". **Each item must start with
      `-`** (the v01 grader literally asserts `arg.startswith("-")` on every item, so a
      flag and its value(s) go in ONE item: `"--indent 2"`, `"--arg name value"`). When
      you need no options, write `args: []` — an empty list passes that check vacuously.
  - `/app/cmd.sh`: the exact `jq … > /app/out.json` command line, including the output
    redirection (single command line; no shebang, no extra content).
- The checker reconstructs and runs this exact command (verified byte-for-byte on v01):
  `jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/in.json > /app/out.json`
  The `$(...)` for args is unquoted, so **each `args` item is whitespace-split back into
  argv tokens**: the combined item `--indent 2` reaches jq as two correct tokens while
  staying one dashed string inside YAML (both `["--indent 2"]` and `[]` verified
  end-to-end through this exact template). The filter is expanded inside double quotes, so
  its content is not re-parsed by the shell — double quotes and `$var` inside the filter
  are safe; the only thing to escape is the YAML layer (see Packaging).
- The output format (indentation, separators, key order) is specified in the instruction; jq's
  default pretty-printer already indents 2 spaces (byte-identical to `--indent 2` on jq 1.6),
  and `--indent N` changes it. Do not use `-r`/`-c` for the report unless asked.
- Observed v01 grader structure (mirror it before finishing; every content/replay test passed
  when these were honored): it parses `jq_args.yaml` per the bullet above, then **re-runs
  BOTH `bash cmd.sh` and the yaml-reconstructed command against the original input AND
  against adversarially mutated inputs** (missing/blank/non-string/null fields), comparing
  the output to an expected transformation; it also checks the input file hash is unchanged
  — never modify the input JSON in place. All robustness must therefore live inside the
  filter itself (`//`, type guards, blank checks), which is exactly what the stage skeleton
  below encodes.

## What varies (the four variation axes from the family spec)

1. **Selection & ordering** — which records survive (multi-field predicates, inclusion +
   exclusion rules, predicates on *derived* values) and the final array order (multi-key,
   descending, ordering on derived keys).
2. **Field derivation & reshaping** — renamed fields, flat vs nested output, deep/optional
   access, several source fields merged into one output field, structures very different
   from the input.
3. **Value normalization** — trim/lowercase, extracting parts of structured strings, date →
   `YYYY-MM-DD`, numeric coercion, boolean derivation, fallback defaults, null propagation.
4. **Aggregation & collection ops** — per-record counts, first/last picks, grouping,
   deduplication, flattening/rebuilding arrays, collection-level summaries, possibly
   per-record transformation *and* cross-record aggregation in one jq program.

### Variation coverage map — match the spec's phrases to concrete mechanisms

When a variant deviates from v01, locate its requirements in this map and reuse the
referenced idioms (every snippet verified on jq 1.6 in the harness container; anything
further is extrapolation — spot-test first).

- **Selection interacting with derived values**: bind at STAGE 1 and select on the binding —
  `(($roles | length) as $n | select($n > 1))`; membership sets:
  `select($v == "admin" or $v == "owner")`, `select($list | index($v) == null)`,
  `IN`: `select(IN("a","b"))`; universal/existential across several fields:
  `([.a,.b,.c] | any)`, `([.a,.b,.c] | all)`.
- **Reshaping** — renames `{new: .old}`; merged-from-many: `"\(.a) <\(.b)>"`, `[.a, .b]`,
  `(.a + "/" + .b)`; nested literals `{k: {sub: …, arr: […]}}`; optional/deep: `.a?.b?.c // f`;
  key remapping/picking: `to_entries | map(select(cond)) | from_entries` (entries must keep
  `key`/`value` names) or `with_entries(.value |= f)`; deep shape transforms: `walk(f)`
  (applies f to every node; guard inside f with `type ==` checks).
- **Value normalization** — table below, plus: numeric formatting `round`, scaling
  `(. * 1000 | round) / 1000`; boolean derivation `(.x == "true")`, `(($list|length) > 0)`,
  `(if .x == null then false else .x end)`.
- **Aggregation/collection** — counts: `length`, `[stream | select(cond)] | length`; picks:
  `($a[0] // null)`, `($a[-1] // null)`, `first(.[] | select(cond)) // null`; grouping:
  `sort_by(.k) | group_by(.k) | map({k: .[0].k, n: length, sum: (map(.v) | add)})`; rebuild
  arrays: `flatten`, `[.[] | .arr[]]`; extrema: `min`, `max`, `min_by(.k)`, `max_by(.k)`;
  arbitrary folds: `reduce .[] as $r ({}; .[$r.k] = ((.[$r.k] // 0) + $r.v))`;
  per-record + summary in one program: (. | map(PER_RECORD) as $records | …);
  count-conditional shape: `if length == 1 then .[0] else . end` or
  `first(.[] | select(cond)) // null`; extra input files: read them in args as one dashed
  item and index the variable — `args: ["--slurpfile extra /app/other.json"]` then
  `$extra[0][.id]` (verified through the reconstruction template).

## Workflow (follow in order)

### 1. Re-read and parse the instruction into an explicit checklist

Write down, in the instruction's words:
- every **selection predicate** (e.g. status equals X; has privileged role *after
  normalization*; exclude if derived value Y appears in list Z),
- every **normalization rule** with its *timing* ("normalize before checking, before
  deduplicating, before sorting" — orderings like this are testable and matter),
- every **output field** with exact key names and exact value form (pay attention to
  "exact form `username <email>`", required key renames like `id` → `user_id`),
- the **ordering** spec (keys + directions, ties unspecified ⇒ keep it deterministic anyway),
- the **formatting** spec (indentation).

Note which values are used *as-is* (e.g. `username`, `email` stay original) vs *normalized in
output* (e.g. `email_domain` is the lowercase part after `@`). Never trim/lowercase original
fields just because a related normalization exists.

### 2. Inventory the input before writing the filter

```bash
jq 'type, length' input.json                 # top-level: array? object? how many?
jq '.[0]' input.json                          # one record, full key vocabulary
jq -c 'group_by(.status)|map({s: .[0].status, n: length})' input.json
# for every field you will touch: nulls, absent keys, empty arrays, whitespace-only, types:
jq '[.[] | select(.phone == null or (.phone | type != "string"))] | length' input.json
jq '[.[] | select((.roles // [] | length) == 0)] | length' input.json
jq -r '[.[].email | split("@")[-1] | ascii_downcase] | unique | join(", ")' input.json
jq -r '[.[].roles[] | gsub("^[[:space:]]+|[[:space:]]+$";"") | ascii_downcase] | unique | join(", ")' input.json
```

Decide per field what "missing/blank/empty" means for THIS task before coding
(whitespace-only string counts as blank after trimming; `|| length == 0` handles a `null`
array too because `length` of `null` is `0`).

### 3. Build the filter as normalize → filter → shape → cross-record stages

Fixed skeleton (this ordering avoids every classic bug):

```jq
map(
  # STAGE 1 — bind normalized/derived values ONCE with `(EXPR) as $v |`; use only these downstream.
  (.roles // [] | map(select(type == "string")) | map(NORM)) as $roles
  | ((.email | split("@")[-1] | ascii_downcase) as $domain
  | (((.x.y? // "fallback") | tostring) as $x
  | (
  # STAGE 2 — all select() filters, one per line, using the bound variables.
      select(.status == "active")
  |   select([$roles[] | select(. == "admin" or . == "owner")] | length > 0)
  |   select($blocked | index($domain) == null)
  # STAGE 3 — one object literal; key order = output order; nested objects/arrays fine.
  |   {out_key: .src_key, derived: ..., nested: {…}}
  # (…are placeholders — substitute your own keys/expressions)
  # close all parens opened by the as-bindings
  ))))
# STAGE 4 — cross-record operations (sorting, grouping, aggregation) at top level.
| sort_by(.key1)
| …
```

**Grammar pitfall (hit once, hit hard in v01):** chained `as` bindings *must* be
parenthesized — write `(A) as $v | (B) as $w | …`, never `A as $v | B as $w | …`.
Unparenthesized chains misparse and produce baffling errors like `Cannot index array with
string`. Count your closing parens before the final stage.

Ideas per axis:

- **Selection on derived values** — bind first (`$roles`, `$domain`, counts like
  `($roles|length) as $n`), then `select(...)` on the variables. Exclusion lists:
  `select([$list[] | select(NORM == $val)] | length == 0)` or
  `select($list | index($value) == null)`. Use `index` **not** `contains` for whole-element
  equality (`contains("ab")` also matches `"xaby"` — confirmed substring surprise).
- **Reshaping** — `{id: .id}` renames; `{contact: "\(.username) <\(.email)>"}` merges
  fields; `[.a, .b]` packs values into an array; deep/optional access via `.a?.b?.c` (or
  `.a.b // "x"`, which jq special-cases safely for null intermediates); conditional shape
  with `if … then … elif … else … end`; merge inputs with `+` (shallow) or `*` (recursive).
- **Normalization** — see the idiom table below; there is **no `trim` builtin** on jq 1.6
  (verified: `trim/0 is not defined`); use `gsub("^[[:space:]]+|[[:space:]]+$";"")`.
- **Dates** — when the output is the calendar date from an ISO string, take the prefix:
  `.last_login | split("T")[0]`. Verified pitfall: on jq 1.6 `fromdateiso8601` **errors on
  fractional seconds** (`does not match format %Y-%m-%dT%H:%M:%SZ`); if you truly need
  epoch/UTC conversion, strip the fractional part first (`split(".")[0] + "Z" | fromdateiso8601
  | strftime("%Y-%m-%d")`), and remember `strftime` outputs UTC.
- **Aggregation/counting** — `length` on an array; `[stream | select(cond)] | length` for
  conditional counts; `sort | unique` (or `unique`, which sorts + dedups on 1.6 — verified);
  `group_by(.k) | map({k: .[0].k, n: length})`; `flatten` to rebuild arrays;
  `add`/`min`/`max` for collection summaries; first pick: `($list[0] // null)`.
- **Per-record + summary in one program** — keep it in one jq invocation:
  ```jq
  (. | map(per_record_stages) as $records
    | {records: $records, summary: ($records | cross_record_aggregation)})
  ```
  or append: `$records + [$records | cross_record_aggregation]` when the spec wants a
  trailing summary row. A flat array of one kind plus a summary object is also fine —
  whatever the instruction sketches; the key is using jq only, one command.

**Normalization idiom table** (with default handling built in):

| Need | jq (all verified on jq 1.6) |
|---|---|
| trim whitespace | `gsub("^[[:space:]]+|[[:space:]]+$"; "")` (no `trim` builtin!) |
| lowercase/uppercase ASCII | `ascii_downcase` / `ascii_upcase` (non-ASCII untouched); **errors on non-strings** — guard: `((.x // "") | tostring | ascii_downcase)` |
| domain of an email | `((.email // "") | tostring | split("@")[-1] // "" | ascii_downcase)` — the `[-1] // ""` also survives a missing `@` (`"" | split("@")` is `[]`); if a missing `@` must stay distinct, branch with `if test("@") then … else … end` (test also needs a string input) |
| null/absent → default | `.a?.b // "x"`; arrays: `.roles // []`; blanks: `if $v == "" then "unknown" else $v end` |
| non-string scalars → string | `tostring` for scalars; **`tostring` alone maps `null`→`"null"`**, so always `(.x // "") | tostring` first |
| numeric coercion w/ fallback | `(tonumber? // 0)` (`?` suppresses the error) |
| string parts | `((.x // "") | tostring | split("|")[k])`, capture regex via `capture("(?<a>…)-…").a // null`, `sub`/`gsub`, `test(regex)` — these all error on non-strings (see pitfall list) |
| boolean derivation | `(.flag == "true")`, `(($list | length) > 0)` |
| date to YYYY-MM-DD | `((.last_login // "") | tostring | split("T")[0] // "")` — fallback BEFORE `tostring` (else `null`→`"null"`); `("" | split("T"))` is `[]`, so the trailing `// ""` resists blank dates where plain `[0]` would be `null` |

### 4. Ordering: mixed-direction multi-key sorts that never lie

Rules, all verified on jq 1.6 (stress-tested with 1000 grouped records):

- `sort_by` is **stable** on jq 1.6 (confirm in your env with the one-liner below). Chain
  one `sort_by` per key, applying the **most significant key LAST** so stability freezes the
  earlier relative order within equal keys:
  ```jq
  # email_domain ASC, then username DESC:
  sort_by(.username) | reverse | sort_by(.email_domain)
  ```
- **Stability-free variant** (works even if `sort_by` proves unstable):
  ```jq
  sort_by(.email_domain) | group_by(.email_domain) | map(sort_by(.username) | reverse) | flatten
  ```
  (`group_by` sorts its input first on 1.6, and this variant reproduced the two-pass bytes
  exactly.) Prefer this variant when the harness environment is unknown.
- For **descending strings use `reverse`**; do not negate codepoints (`explode | map(-.)`) —
  that trick silently inverts prefix relationships ("ab" vs "abc").
- Sort **numbers** with `sort_by(tonumber)` if the sort key may stringify numbers; use
  `(| sort)` only on homogeneous key types (mixed types throw).
- String comparison = Unicode codepoint order; `sort`/`sort_by` place `null`/missing keys
  first — coerce with `// ""` when that matters.
- Tie-break determinism: if the spec gives no tie-breaker, the stable sort keeps input order
  — fine. Never rely on hash order.
- Stability smoke test for any environment:
  ```bash
  jq -n -c '[range(0;1000) as $i | {d: (["a","b","c","d","e","f","g"][$i % 7]), u: ($i|tostring)}] | sort_by(.u) | reverse | sort_by(.d) | group_by(.d) | map(select((map(.u)) != (map(.u) | sort | reverse))) | length'  # expect 0
  ```

### 5. Incremental build + stage-count checks

Grow the filter stage by stage and check the count shrinks only as the spec intends:

```bash
jq -c 'STAGE1_FILTER' input.json | head -3              # per-stage eyeball
jq 'FILTER(only-selects, no shaping)' input.json | jq 'length'   # expected survivor count?
```

Work out the expected survivor count with the unix `jq` one-liner *before* shaping to catch
filter mistakes early (v01: 500 → 203). Also test the degenerate cases explicitly:
empty input (`echo '[]' | jq 'FULL_FILTER'`), a hand-made record with nulls/blanks/dup
roles, and confirm output stays valid JSON and in the required order.

### 6. Cross-validate (verification only — the report must come from jq)

A tiny reference in another language that implements *your reading* of the instruction and
compares with the jq output catches spec misreadings better than anything. Keep it outside
`/app` (e.g. `/tmp/refcheck.py`), never write the report with it, and delete it. Compare the
**parsed structure** across languages (load both and compare objects), not bytes: e.g.
Python's `json.dump(..., indent=2)` matches jq's spacing but omits jq's trailing newline, so
byte-diffs across languages are noise. Reserve `cmp` for jq-vs-jq determinism checks. If you
prefer jq-only checks: verify record count, `group_by(.email_domain)|map(length)`, per-group
username order (`map(.username) == (map(.username)|sort|reverse)` for each group), no
duplicates in `roles`, `role_count == (roles|length)`, and spot-check 2–3 records by hand.

### 7. Package the artifacts and verify byte-level

1. Write the jq program as a **single line** containing **no single quotes** (use
   double-quoted literals like `"admin"`, `"unknown"` inside jq: they are safe in both
   packaging layers and in `cmd.sh`'s single-quoted wrapping).
2. `jq_args.yaml` — a YAML single-quoted scalar for `filter`; `args` as a flow/block list of
   dash-prefixed items, one complete option invocation per item:
   ```yaml
   filter: 'map( ...jq program without single quotes... ) | sort_by(...)'
   args:
     - "--indent 2"
   ```
   Or, when no options are needed at all:
   ```yaml
   filter: 'map( ...jq program without single quotes... ) | sort_by(...)'
   args: []
   ```
   Keep only the two keys. Rules, all consequences of the grader contract:
   - **Every item starts with `-`**; never split a flag from its value across items
     (`["--indent", "2"]` fails the `arg.startswith("-")` assertion and cost the anchor
     run its only failed test).  Combine instead: `"--indent 2"`, `"--arg name value"`,
     `"--slurpfile f /path/name.json"`, `"-n"`.
   - Use args only for real jq options; never put the filter or `-f` there — the template
     already injects the filter as an argument.
   - When the format spec states an indentation N, prefer the explicit `"--indent N"` item
     (verified byte-identical to jq's default for N=2, but explicit is safer across
     versions); otherwise prefer `args: []`.
   - A flag value containing spaces cannot be carried through this interface at all
     (each item is whitespace-split). Bind such literals inside the filter instead:
     `("value with spaces") as $v | …`.
3. `cmd.sh` — exactly one line, the exact command you validated (filters single-quoted,
   absolute paths, redirection included):
   ```bash
   jq --indent 2 'map( ...same filter... ) | sort_by(...)' /app/input.json > /app/output.json
   ```
4. Run the checker's reconstruction verbatim (from `/app`) and prove reproducibility:
   ```bash
   cd /app
   jq $(yq -r '.args[]' jq_args.yaml) "$(yq -r '.filter' jq_args.yaml)" input.json > /tmp/a.json
   bash cmd.sh
   cmp /tmp/a.json output.json && echo IDENTICAL     # bytes, not just parsed equality
   jq 'length' output.json                            # sanity count
   sed -n '1,8p' output.json | cat -A                 # verify indentation (2 spaces), no tabs/CR
   ```
   If `cmp` fails but parsed JSON matches, your command is non-deterministic — fix that (sort
   ties, stable grouping), because byte-level graders exist.

5. Rehearse the checker's own validation of `jq_args.yaml` (these mirror the observed v01
   assertions and must all hold):
   ```bash
   yq -r '(. | keys | sort) == ["args","filter"]' jq_args.yaml    # → true
   yq -r '.filter | type' jq_args.yaml                             # → "string"
   yq -r '.args | type' jq_args.yaml                               # → "array"
   yq -r '[.args[] | type] | all(. == "string")' jq_args.yaml      # → true
   yq -r '[.args[] | startswith("-")] | all' jq_args.yaml          # → true (empty list passes vacuously)
   ```

## Pitfall checklist (all confirmed on jq 1.6 unless marked)

- Unparenthesized chained `as` bindings misparse → `Cannot index array with string`.
- `contains` does substring matching; use `index($v) == null` or `==` for exact membership.
- `tostring` on `null` yields `"null"`; use `// ""` before `tostring`.
- `split`, `gsub`, `ascii_downcase`, `test`, `capture` all **throw on non-string input** —
  `// ""` only guards null/absent, not numbers or booleans. Always chain the coercion:
  `(.x // "") | tostring | …`. (Observed live: mutated inputs with null/numeric emails
  failed with `split input and separator must be strings`.)
- `("" | split(SEP))` returns `[]` on jq 1.6 — NOT `[""]` — so `split(SEP)[0]` is `null`
  for blank inputs. Append `// ""` after the `[0]` when the spec wants `""` for
  missing/blank values instead of `null`.
- No `trim`/`ltrim`/`rtrim` builtins on 1.6; use `gsub` with `[[:space:]]`.
- `fromdateiso8601` errors on fractional seconds on 1.6; `split("T")[0]` for the date part.
- `explode|map(-.)` ordering trick is broken for prefix strings; use `sort_by | reverse`.
- `sort`/`unique` on mixed types (number + string) throws; coerce first.
- `[$roles[] | select(...)]` needs the brackets; `$roles[] | select(...)` alone returns a
  stream, and a bare `select` in a comma expression drops records unexpectedly.
- In `map(...)`, `$vars` bound outside with `as` are visible inside, but rebinding inside
  `map` a value computed per-record must happen per-record — compute Stage-1 bindings inside
  `map`, not before it.
- `as` bindings bind *values*, not paths: later changes (e.g. `|=`) don't update the variable.
- **Every `args` item must start with `-`** (grader assertion). Splitting a flag from its
  value — `["--indent", "2"]` — runs fine yet fails that check; that exact mistake lost
  the only failed test (13/14) on the anchor eval. Combine into ONE item: `"--indent 2"`.
- A flag value containing spaces is not representable in `args` (each item is
  whitespace-split by the unquoted expansion); bind such literals inside the filter:
  `("value with spaces") as $v | …`.
- The grader replays BOTH saved commands against adversarially mutated inputs — build every
  `//` fallback, `select(type == …)` guard, and blank check into the filter itself; never
  pre-clean the input file (its hash is checked).
- A single quote inside the filter breaks `cmd.sh`'s single-quoted wrapping; in YAML a single
  quote must be doubled even in single-quoted scalars — avoid entirely.
- Writing extra top-level keys into `jq_args.yaml` (e.g. `input:`) is a contract violation.
- `-r`/`-c` on the report command destroys the required indentation.
- `group_by` on unsorted input: jq 1.6 sorts first, but do not count on that in other
  versions (gojq behaves differently) — chain `sort_by` before `group_by` for portability.
- Extra prose/echoes/newlines in `cmd.sh` beyond the one command line ("the exact jq command
  you execute") can fail exact-content checks.

## Worked example (anchor case compose-all; adapt, do not copy)

Task: filter `active` accounts having role `admin`/`owner` *after* trim+lowercase, excluding
any account whose lowercase email domain is in its normalized blocked list; phone trimmed
else `"unknown"`; `last_login` → date; summary `{role_count, primary_role, roles}` from the
normalized deduped sorted roles; final order `email_domain ASC, username DESC`; indent 2.
Every binding below was verified end-to-end against a byte-identical independent reference.

```jq
map(
  (.roles // [] | map(select(type == "string")) | map(gsub("^[[:space:]]+|[[:space:]]+$"; "") | ascii_downcase)) as $roles
  | (((.email // "") | tostring | split("@") | (.[-1] // "") | ascii_downcase) as $domain
  | ((.blocked_domains // [] | map(select(type == "string")) | map(gsub("^[[:space:]]+|[[:space:]]+$"; "") | ascii_downcase)) as $blocked
  | (((.phone // "") | tostring | gsub("^[[:space:]]+|[[:space:]]+$"; "")) as $phone
  | (($roles | sort | unique) as $sorted
  | select(.status == "active")
  | select([$roles[] | select(. == "admin" or . == "owner")] | length > 0)
  | select($blocked | index($domain) == null)
  | {user_id: .id,
     username: .username,
     email: .email,
     email_domain: $domain,
     contact: "\(.username) <\(.email)>",
     phone: (if $phone == "" then "unknown" else $phone end),
     last_login: ((.last_login // "") | tostring | split("T")[0]),
     account_summary: {role_count: ($sorted | length),
                       primary_role: ($sorted[0] // null),
                       roles: $sorted}})))))
| sort_by(.username) | reverse | sort_by(.email_domain)
```