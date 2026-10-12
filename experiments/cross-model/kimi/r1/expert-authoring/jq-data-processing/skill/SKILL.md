---
name: jq-data-processing
description: >-
  Transform a JSON record file into a filtered, normalized, reshaped, and
  sorted report using jq (1.6), and produce the required audit artifacts
  (cmd.sh with the exact command, jq_args.yaml with filter/args) so that a
  grader can reconstruct and byte-compare the output. Covers multi-condition
  selection, inclusion/exclusion logic, multi-key and descending ordering,
  field renaming/reshaping, nested summaries, per-value normalization
  (trim/case/date/defaults), and collection operations (dedup, count, group).
---

# jq Data Processing

You are given a JSON file of records and a precise report specification, and
must produce: (1) the transformed output JSON, (2) `/app/cmd.sh` holding the
exact command including output redirection, and (3) `/app/jq_args.yaml`
holding `filter` and `args` from which the grader rebuilds the command.
The transformation **must be jq** — never produce the report with another
language. Graders typically byte-compare the output against a reference, so
exactness (key names, key order, value formats, sort order, indentation,
fallbacks) is the whole game.

## Workflow (follow in order)

1. **Read the instruction twice; write down an exact spec sheet.** Extract:
   input path, output path, selection predicate(s), exclusion predicate(s),
   every output field with its *exact* name and derivation rule, every
   normalization rule and *when it applies* (before compare? before dedup?
   before sort?), nested structure, final sort keys *with direction*, and
   formatting (indent). Ambiguity about ordering of operations is resolved by
   the instruction's words — e.g. "normalize before checking, before
   deduplicating, and before sorting" means one normalized value drives all
   three.
2. **Inspect the actual data before writing the filter.** Never assume values
   are clean or that fields exist. Run quick probes (see below).
3. **Build the filter incrementally**, testing each stage on the real input.
4. **Generate the output and verify it independently** (checklist below).
5. **Write the two artifacts, then re-run the reconstruction and byte-compare**
   (see "Artifact contract"). The packaged script does steps 0–2 of the
   checklist in one shot — run it before finishing:
   `bash /skill/scripts/verify_artifacts.sh INPUT OUTPUT /app/jq_args.yaml /app/cmd.sh`
6. **Run dependent shell commands in ONE invocation, chained with `&&`.**
   Never issue a producer (reconstruction write) and its consumer (`cmp`,
   checks) as separate parallel tool calls — the consumer can run first and
   report phantom mismatches, tempting you to "fix" correct artifacts.

## Data probes (always run)

```bash
jq 'length' IN.json                                   # record count
jq '.[0]' IN.json                                     # shape of one record
jq -r '[.[].someField | type] | unique' IN.json       # null? string? number?
jq -r '[.[].status] | unique' IN.json                 # exact categorical values / casing
jq '[.[] | select(.listField == null or (.listField|length)==0)] | length' IN.json
jq -r '[.[].strField | test("^\\s|\\s$")] | any' IN.json   # stray whitespace?
```

Match predicates to *observed* values (e.g. is status `"active"` or
`"Active"`?), but implement the rules the instruction states.

## Environment facts (verified on jq 1.6 — design for it)

- **No `trim`, `ltrim`, `rtrim`** (those are jq 1.7+). Use
  `gsub("^\\s+|\\s+$"; "")` or `sub("^\\s+";"") | sub("\\s+$";"")`.
- Lowercase/uppercase: `ascii_downcase` / `ascii_upcase`. They error on
  `null` — guard with `// ""` or only apply to known strings.
- `sort_by` is **stable** and `sort_by([k1, k2])` compares key arrays
  ascending only. Multi-key direction playbook (verified on jq 1.6):
  - all ascending: `sort_by([.k1, .k2, .k3])`
  - all descending: `sort_by([.k1, .k2]) | reverse`
  - a *numeric* key descending among ascending ones: negate it —
    `sort_by([.k1, (-.k2)])`
  - outer asc, inner desc (strings): `sort_by(.inner) | reverse | sort_by(.outer)`
  - outer desc, inner asc (strings): `sort_by(.inner) | group_by(.outer) | reverse | add`
  - WARNING: `sort_by(k) | reverse` reverses the WHOLE array, destroying any
    previously established less-significant ordering — the `reverse` trick is
    only safe on the FIRST (least significant) key you apply. Always verify
    mixed-direction sorts by extracting the keys (`@tsv`) and checking
    adjacent pairs.
- `unique` sorts ascending *and* dedups in one step; `unique_by(f)` likewise.
  `sort` on strings is bytewise (uppercase < lowercase) — normalize case first
  if the spec demands case-insensitive ordering.
- `//` (alternative) triggers on `null` **and `false`** — do not use it to
  default boolean fields; use `if .x == null then ... else .x end`.
- `tonumber` throws on bad input; use `tonumber?` or `try ... catch ...`.
  `tostring` on `null` yields `"null"` — usually guard first.
- Missing keys read as `null`; `null` propagates silently through path
  traversal (`.a.b.c` on missing data is `null`, no error), but errors through
  string functions like `ascii_downcase`/`gsub` (`null | length` is 0, but
  `null | ascii_downcase` throws). Safe rule: apply `// <default>` at
  extraction time for any optional field *before* piping into string ops.
- ISO 8601 → `YYYY-MM-DD`: prefer pure string slicing `split("T")[0]` or
  `.[0:10]` when the input is well-formed; `strptime`/`strftime` in 1.6 have
  timezone/locale pitfalls. Check all values match the expected shape first:
  `jq -r '[.[].ts | test("^\\d{4}-\\d{2}-\\d{2}T")] | all' IN.json`.

## Canonical filter skeleton

Structure the program as: helper `def`s, one big `[ .[] | select(...) | {...} ]`
pipeline, then the final sort. Bind every derived value **once** with `as`
and reuse the binding — this is what keeps "normalize before compare/dedup/sort"
consistent:

```jq
def nrm: gsub("^\\s+|\\s+$"; "") | ascii_downcase;     # adapt to spec
[
  .[]
  | select(<predicate on raw or derived values>)
  | . as $u
  | ($u.roles // [] | map(nrm)) as $nroles              # derived collection
  | select($nroles | any(. == "admin" or . == "owner")) # inclusion on derived
  | ($u.email | split("@")[1] | ascii_downcase) as $dom
  | select(($u.blocked_domains // [] | map(nrm)) | index($dom) | not)  # exclusion
  | ($nroles | unique | sort) as $roles                 # dedup+order after nrm
  | {
      user_id: $u.id,                                    # rename
      username: $u.username,                             # passthrough
      email_domain: $dom,                                # derived scalar
      contact: "\($u.username) <\($u.email)>",           # combine fields
      phone: (($u.phone // "") | gsub("^\\s+|\\s+$";"")  # default + cleanup
              | if . == "" then "unknown" else . end),
      last_login: ($u.last_login | split("T")[0]),       # format conversion
      account_summary: {                                 # nested summary object
        role_count: ($roles | length),
        primary_role: ($roles[0] // null),               # null when empty
        roles: $roles
      }
    }
]
| sort_by(.username) | reverse | sort_by(.email_domain)  # mixed-direction sort
```

Adapt names/rules to the task; keep the skeleton shape.

## Recipes by variation axis

**Selection & ordering.** Compose predicates with `and`/`or`/`not` inside one
`select`, or chain `select`s for readability (AND semantics). For "any element
satisfies": `select(.xs | any(. == v))`; "none": `... | any(...) | not` or
`index(v) | not`; membership in a literal set: `select(.x == "a" or .x == "b")`
or `select(["a","b"] | index(.x))`. When a criterion uses a *derived* value
(domain, normalized role, computed score), compute it with `as` **before** the
`select` that consumes it. Multi-key same-direction: `sort_by([.a, .b])`.
Mixed direction: stable-sort composition (above). Never rely on input order.

**Field derivation & reshaping.** Rename by `newname: .old`. Combine fields
with interpolation `"\(.a) <\(.b)>"`. Deep access: `.a.b.c` — guard optional
parents with `(.a // {}).b` or `.a.b?` — and put `// default` at the leaf when
the spec defines a fallback. Nested output objects are just object literals
inside the record literal; nested output arrays come from `map(...)` over a
source array. jq emits object keys in construction order — write them in the
order the spec lists them in case the comparison is textual, and verify with
`keys_unsorted` (plain `keys` sorts alphabetically and misleads).

**Value normalization.** Trim: `gsub("^\\s+|\\s+$";"")`; case: `ascii_downcase`;
extract part of a structured string: `split("@")[1]`, `capture("...")`,
`sub(...)`; numeric coercion: `tonumber?` then `// default`; boolean
derivation: a plain comparison expression (never string-compare booleans);
fallback chains: `(.x // "") | cleanup | if . == "" then "unknown" else . end`;
null propagation: if the spec says "null stays null", don't default it — use
`(if .x == null then null else (.x | f) end)`. Apply the *same* normalization
function everywhere the spec says "normalized", including inside comparisons.
Make normalizers **type-total** when it costs nothing — adversarial replays
mutate value types: `(.x // "") | tostring | gsub(...)` survives a number where
`(.x // "") | gsub(...)` crashes (`tostring` is identity on strings). For
string arrays, `(.xs // []) | map(strings | nrm)` silently drops non-string
elements instead of crashing — a deliberate, usually-correct choice when the
spec assumes strings; decide drop-vs-keep consciously, not by accident.

**Aggregation & collections.** Per-record: `length` for counts, `.[0] // null`
for first, `unique | sort` for dedup+order, `map(f)` to rebuild, `add` /
`add / length` for sums/means (guard empty with `// 0` as spec dictates).
Cross-record, when the spec asks for grouping or collection-level summaries:
`group_by(.key)` then `map({key: .[0].key, items: ..., n: length})`;
`flatten` for nested arrays; `INDEX(.id)` / `GROUP_BY` (1.7+; avoid) — prefer
`group_by`. Note `group_by` SORTS groups by the key — if the spec wants a
different output order (e.g. by group size descending), re-`sort_by` after
grouping. Combine per-record and cross-record work by wrapping: compute the
per-record array first, then aggregate over it as the final stage.

## Artifact contract (must both reproduce the output byte-for-byte)

The grader reconstructs the run as:

```
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" INPUT > OUTPUT
```

Rules that keep this safe:

- `jq_args.yaml` has **exactly** the keys `filter` (string) and `args` (list of
  strings). Write `filter` as a YAML block scalar (`|-`) so quoting/escaping is
  a non-issue. Sanity-check extraction with `yq -r '.filter' jq_args.yaml` and
  `yq -r '.args[]' jq_args.yaml`, then prove correctness by running the
  reconstruction line itself.
- `args`: **HARD RULE — every list item must be a single string that starts
  with `-`.** A flag and its value are ONE item, never two. Validators assert
  `arg.startswith("-")` for each item, so this fails:
  ```yaml
  args:            # WRONG — "2" does not start with "-"
    - "--indent"
    - "2"
  ```
  Write it as one combined item; the unquoted `$(...)` word-splitting in the
  reconstruction template turns it back into the two tokens jq needs:
  ```yaml
  args:            # CORRECT
    - "--indent 2"
  ```
  Simplest of all: if the default jq behavior already satisfies the spec
  (jq's default indentation IS 2 spaces), `args: []` is valid and sidesteps
  the whole hazard — but only use it when truly no flags are needed.
  **Never** put a value containing spaces that must survive as one shell word
  into an arg item — word splitting will corrupt it. Inline such values into
  the filter string instead of using `--arg`.
- `cmd.sh`: the literal command you executed, including `> OUTPUT`. Single-quote
  the filter — so **keep the jq filter free of apostrophes** (jq strings use
  double quotes anyway). Multi-line single-quoted strings are legal in bash.
  Make `cmd.sh` and `jq_args.yaml` describe the *same* filter and flags.
- Default jq indentation is already 2 spaces; passing `--indent 2` explicitly
  is harmless and self-documenting — match whatever the spec demands.
- Observed grader behavior (v01): it **replays both `cmd.sh` and the
  reconstructed command against adversarial variants of the input** (mutated
  fields, nulls, edge cases). Your filter must not crash and must follow the
  spec on such inputs: guard every optional field (`// []`, `// ""`), never
  assume a key exists, and make exclusion/fallback logic total. This is why
  the skeleton's guards are mandatory, not decorative.

## Self-verification checklist (do all, then re-run)

0. Lint the YAML artifact shape (catches the most common grader failure):
   `yq -r 'keys' jq_args.yaml` shows exactly `[filter, args]`; and
   `yq -r '.args[]' jq_args.yaml | grep -v '^-'` prints NOTHING (every arg
   item starts with `-`; a bare value like `2` on its own line is an
   automatic fail).
1. `bash /app/cmd.sh` succeeds and writes the output file.
2. Run the reconstruction line above into a temp file; `cmp` it with the output
   file — must be identical. The packaged helper does this plus the cmd.sh
   re-run (the skill mount is read-only, so invoke via bash):
   `bash /skill/scripts/verify_artifacts.sh INPUT OUTPUT /app/jq_args.yaml /app/cmd.sh`
   (If the skill is mounted elsewhere, use that path; the script sits next to
   this SKILL.md as `scripts/verify_artifacts.sh`.)
3. Count stages independently and reconcile:
   `jq '[.[] | select(<pred>)] | length' IN` vs `jq 'length' OUT`, and per
   exclusion rule: `jq '[.[] | select(<violates exclusion>)] | length' OUT` → 0.
4. Ordering: extract the sort keys (`jq -r '.[] | [.k1,.k2] | @tsv' OUT`) and
   confirm ascending/descending per spec; verify normalization was applied
   before sorting (case, trim).
5. Every output key present with exact spelling; spot-check 2–3 records
   field-by-field against derivations done by hand; check fallback branches
   fired the right number of times (e.g. count of `"unknown"` phones equals
   count of missing/blank phones in input). Check **key order** with
   `jq 'keys_unsorted'` — plain `keys` SORTS alphabetically and will trick you
   into "fixing" output that is already correct.
6. Format checks: regex-validate formatted values (dates `^\d{4}-\d{2}-\d{2}$`),
   confirm indentation (`head -3 OUT`), confirm output is an array (or object)
   as specified.
7. Re-run everything from the artifacts (not from your scratch filter) as the
   last step so the on-disk output is provably produced by the stored command.

## Common failure modes

- Splitting a flag and its value into two `args` items (`["--indent", "2"]`) —
  the validator rejects items not starting with `-`. One item: `["--indent 2"]`.
- Normalizing for the comparison but sorting/deduping the raw value (or vice
  versa) — one `nrm` binding feeds all uses.
- Using `trim` (jq 1.7-only) — syntax error at runtime: "trim/0 is not defined".
- `sort_by([a,b])` when `b` must be descending — array keys sort ascending only.
  And `sort_by(k) | reverse` mid-chain (after another sort) silently destroys
  the inner ordering — use the verified multi-key direction playbook.
- `//` swallowing legitimate `false`/`0`? (`0 // x` keeps 0; `false // x` → x.)
- Apostrophes in the jq filter breaking the single-quoted `cmd.sh` command.
- `--arg name "value with spaces"` as one yaml item — word splitting corrupts it.
- Producing output with a scratch command, then hand-editing artifacts that
  don't match it — always regenerate from the final artifacts.
- Forgetting the output redirection inside `cmd.sh`, or omitting `args`/`filter`
  keys from `jq_args.yaml` (validator asserts the key set is EXACTLY those two).
- Unguarded field access that crashes when the grader replays the command on
  adversarial inputs (null phone, missing roles, empty arrays) — keep every
  `// []` / `// ""` guard from the skeleton.
- Trusting `jq 'keys'` to check output key order — it sorts; use `keys_unsorted`.
- Issuing a reconstruction-write and its `cmp` check as parallel tool calls —
  the check can run before the write lands (phantom "differ"). Chain with `&&`
  in one shell invocation.
