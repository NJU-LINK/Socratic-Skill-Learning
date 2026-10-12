---
name: jq-data-processing
description: >-
  Solve jq-based JSON transformation tasks that read one JSON file, select and
  order records, reshape fields, normalize values, and optionally aggregate
  across records, then deliver a jq program plus the cmd.sh / jq_args.yaml
  packaging contract used to regrade it. Covers derive-once bindings,
  normalize-before-gate/dedup/sort sequencing, blank-vs-missing defaults,
  mixed-direction sorting, the grader-validated jq_args.yaml item contract,
  YAML/shell byte-transparent escaping, and invariant-based verification
  (subpopulation arithmetic, program-wide all predicates, trap-record spot
  checks) so solutions transfer across the
  family's declared variation axes: selection_and_ordering_logic,
  field_derivation_and_reshaping, value_normalization, and
  aggregation_and_collection_operations.
---

# jq-data-processing

Family of tasks: transform a JSON input file into a JSON output file **using
only `jq`**, with the transformation varying over four declared axes:
selection/ordering logic, field derivation/reshaping, value normalization, and
aggregation/collection operations. This skill packages the working method: how
to structure the jq program, how to package it into the grading artifacts, and
how to prove correctness with invariants instead of eyeballing.

Provenance tags: **[v01]** directly verified on the anchor task; **[G]**
grader/oracle evidence from evaluation feedback (the strongest signal
available — e.g. the per-item args rule below); **[T]** teacher-taught
domain knowledge; **[E]** reasoned extrapolation for a spec-declared
variation that was not locally exercised (mechanism, boundary, failure mode,
and a future verification procedure are given where tagged).

## 1. Deliverables and interface (grounded in v01; treat as invariant)

- `/app/<output>.json` — the transformed report, produced by jq alone.
- `/app/cmd.sh` — the **exact** jq command executed, including output
  redirection, so file, executed command, and yaml cannot drift.
- `/app/jq_args.yaml` — exactly two keys:
  - `filter`: the jq filter expression as a string;
  - `args`: list of strings, **every item must start with `-`** [G] — the
    grader asserts `arg.startswith("-")` per item. Flag and value travel in
    ONE self-contained item (`["--indent 2"]` is valid: the
    reconstruction's unquoted `$(yq ...)` expansion word-splits it back into
    argv words). Never split (`["--indent", "2"]` fails the grader on the
    item `'2'` — this was iteration-1's only failed test), and do not
    `=`-join (`--indent=2` is rejected by jq 1.6: "Unknown option"). Prefer
    `args: []` when no flag is truly needed: jq's default pretty-print is
    already 2-space (byte-identical to `--indent 2`), an empty list passes
    every item check vacuously, and it is immune to any reconstruction
    mechanism [v01, G].
- The grader reconstructs and runs:
  `jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" INPUT > OUTPUT`
  Treat this exact line as the contract — anything that works when typed
  interactively but breaks in this line is a packaging bug.

## 2. Workflow

1. **Parse the task into four buckets**: (a) selection predicates + final
   ordering keys/directions, (b) output schema (which fields, nested structure),
   (c) per-value normalization rules, (d) cross-record aggregation.
2. **EDA the input** before writing jq: enumerate statuses/enum values
   (`group_by`), type of every field (`type`), formats (timestamps, emails),
   whitespace/noise, and which fields can be `null` or missing. The seed's
   certified clean shapes are *not* promised for hidden variants (end of §7).
3. **Write the filter** with the derive-once pattern (P1), sequencing (P2),
   and scalar idioms (P3, P5).
4. **Verify with invariants** (§6), then fix and re-verify.
5. **Package** (§5) and run the acceptance test.

## 3. Core patterns

### P1. Derive once, bind once, consume everywhere [v01, T]

Normalize every value exactly once near the top of the per-record pipeline,
bind it with `as $x`, and let *both* the selection gates and the output object
consume the bindings. Never re-derive inline — divergent derivations in the
gate vs. the output are the top source of off-by-one-normalization bugs.

```jq
[ .[]
  | (.roles // []) as $raw
  | ($raw | map(norm)) as $roles          # norm = trim+lowercase
  | (.email // "" | split("@")[1] // "" | ascii_downcase) as $domain
  | ((.blocked_domains // []) | map(norm)) as $blocked
  | select(gates on $roles, $domain, $blocked ...)
  | { output object consuming $roles, $domain, $blocked ... }
]
```

**Guard every field before string/list ops**: `// []` for arrays, `// ""`
for strings, type-guard for scalars (P3). Both grader-passing fresh solvers
used these guarded forms; without them a missing `email` (`null | split`)
or `roles` (`null | map`) crashes the entire run. Iteration-3 mutation smoke
test (missing email / roles / blocked_domains, numeric phone) confirmed:
unguarded variants hard-crash, the guarded filter stays crash-free and
produces valid JSON, and on clean v01 data the guards are identity
(byte-identical output) [v01 + local mutation evidence].

### P2. Normalize → gate → dedup → sort; equality, not substring [v01, T]

When a value must be normalized before comparison/dedup/sorting, the sequence
is a contract, not an implementation detail. `unique` on raw values keeps
`" admin "` and `"ADMIN "` distinct (wrong `role_count`); substring
`contains` lets `superadministrator` pass an `admin` check. Gate with equality
on the normalized values: `select([$roles[] | select(. == "admin" or . == "owner")] | length > 0)`,
membership `select(.x | IN($list[]))`, or `any($list[]; . == $x)`. In v01 the
normalized `unique` also provides the sorted deduped list, and `($roles | unique | .[0])`
yields `null` for an empty list (jq: out-of-range array index → `null`) [v01, T].

### P3. Blank ≠ missing [v01, T]

`//` (alternative operator) only replaces `null`/`false`, not `""`. For
"missing **or blank** → default": `(.x // "") | trim | if . == "" then DEFAULT else . end`.
If hidden variants may carry non-string values (e.g. numeric phone), guard
before string ops: `if (.x | type) == "string" then <trim path> else DEFAULT end`
— exercised in the iteration-3 mutation test: a numeric phone hard-crashes
the unguarded `sub` and yields `"unknown"` with the guard [E, locally
exercised; identity on v01 data, where phones are only null/string].

### P4. Mixed-direction multi-key sorting [v01, T]

`sort_by` is ascending-only; it silently accepts a "descending" misreading
(no error). Canonical mixed-direction pattern (needs no stability assumption):

```jq
| group_by(.email_domain) | map(sort_by(.username) | reverse) | flatten
```

Alternative stable two-pass (jq `sort` is stable): `sort_by(.username) | reverse | sort_by(.email_domain)`.
Notes: numeric descending within a single key: `sort_by(-.n)`; same-direction
multi-key: `sort_by(.a, .b)`. **Reject** the codepoint-negation trick
`sort_by(.s | explode | map(-.))`: it breaks on prefix pairs like `"abc"` vs
`"abcd"` [T].

### P5. Trim + lowercase idiom and the escaping trap [v01, T]

`sub("^\\s+"; "") | sub("\\s+$"; "") | ascii_downcase`

In **jq source**, regex whitespace is `\\s` (two backslashes; jq parses the
string escape, Oniguruma sees `\s`). If the packaged YAML ends up with four
backslashes (`\\\\s`), jq compiles the regex `\\s` = literal backslash +
`s`, which matches nothing — `sub` leaves values untouched, the privilege gate
misses every padded role, and those records **silently vanish from the output
while everything still "looks right"**. The guard is the byte-level test in
§5, never reasoning about quotes.

## 4. Recipe library per spec axis [E unless tagged]

These are transfer recipes for the declared variation dimensions; each has a
verification procedure in §6.

- **selection_and_ordering_logic**: multi-condition `select((.a == "x" or .b == "y") and (.c != "z"))`;
  membership `select(.x | IN($list[]))`; exclusion `select(any($list[]; . == $x) | not)`;
  selection over *derived* values: derive+bind first, then `select` on the
  binding; interaction with intermediate stages: compute the intermediate
  pipeline inside `[...]` before any `group_by`/sort that needs it.
- **field_derivation_and_reshaping**: rename via object literal
  `{user_id: .id, ...}`; deep access `.a.b // null` (jq 1.6; `.?` optional
  chaining is jq 1.7+); combine source fields with interpolation
  `"\(.first) <\(.email)>"` or `join`; nested output objects
  `{summary: {roles: [...]}}`; rebuild collections `[.items[] | {...}]`;
  structure may differ substantially from input — always define the output
  schema explicitly field by field rather than `| .` partial edits.
- **value_normalization**: string cleanup `sub`/`gsub`; structured-string
  extraction `split(delim)[i]` or `capture("(?<x>...)")`; numeric coercion
  `try tonumber catch null` (plain `tonumber` throws on junk); boolean
  derivation via `any`/`all`/comparisons; fallback defaults with `//`
  (remember: `null`/`false` only); null propagation: `if . == null then null else ... end` explicitly;
  ISO timestamps → date: `split("T")[0]` (or `.[0:10]`).
- **aggregation_and_collection_operations**: histogram/grouping
  `group_by(.k) | map({k: .[0].k, n: length, ...})`; dedup `unique` /
  `unique_by(.k)`; flatten `[.[].items[]]` or `flatten`; collection-level
  summaries `{total: (map(.x) | add), ...}`; combined per-record +
  cross-record: compute per-record bindings inside `map(...)`, then
  `group_by` the rebuilt records. Sum-of-parts checks: group sizes sum to the
  row count, group sums sum to the global sum, dedup lengths ≤ input lengths.

## 5. Packaging contract and acceptance test

- `filter`: the jq source **exactly as you would type it inside a single-quoted
  shell argument**. Store as a YAML literal block scalar (`|-`) to preserve
  newlines and backslashes verbatim. The `"$(yq -r '.filter' ...)"` wrapper is
  **byte-transparent**: command-substitution output inside double quotes is
  never re-scanned for backslashes or quotes, so there is no second escape
  layer [T] — verified empirically on v01 [v01].
- `args`: every item must start with `-` [G]; one self-contained item per
  flag with its value (`["--indent 2"]`) — `["--indent", "2"]` fails the
  grader's per-item `startswith("-")` (iteration-1 evidence) and
  `--indent=2` is rejected by jq 1.6. Prefer `args: []` when no flag is
  needed: jq 1.6's default output is already 2-space indent
  (byte-identical to `--indent 2`, verified), and `[]` survives any
  reconstruction mechanism.
- `cmd.sh`: literally the reconstruction line from §1 with real paths. **No
  shebang** (a shebang would change content), then **`chmod +x /app/cmd.sh`**
  — mode bits are part of the deliverable: `+x` changes zero bytes but makes
  the file work under both `bash cmd.sh` and `./cmd.sh` (without it, the
  latter fails with `Permission denied`). Ask of every artifact: does the
  grader *read* it or *run* it, and does its mode match both?

Acceptance test (prove, don't eyeball):

```bash
# 0) grader contract: EVERY args item must start with '-'
#    (empty args prints nothing and is OK; a bare value like '2' fails)
yq -r '.args[]' /app/jq_args.yaml | grep -v '^-' && echo "BAD ARGS ITEM" || echo "ARGS OK"

# 1) byte-check escaping in the yaml: expect exactly TWO backslashes before
#    's' in trim regexes (a run of 4+ is the silent over-escape):
yq -r '.filter' /app/jq_args.yaml | od -c | head

# 2) run the verbatim reconstruction AND the same filter typed directly as a
#    single-quoted arg; they must be byte-identical. Use the SAME args from
#    the yaml for the direct run so the comparison stays fair for any flags
#    (--indent, -r, -c, ...), not just the v01 ones:
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" INPUT > /tmp/a.json
jq $(yq -r '.args[]' /app/jq_args.yaml) 'FILTER_TYPED_DIRECTLY' INPUT > /tmp/b.json
cmp /tmp/a.json /tmp/b.json && echo BYTE-IDENTICAL

# 3) output sanity: valid JSON (v01's output is an array); when the task
#    demands an array, assert the type explicitly and check 2-space indent:
jq -e 'true' /tmp/a.json > /dev/null && jq -e 'type == "array"' /tmp/a.json > /dev/null && head -2 /tmp/a.json
```

`scripts/verify.sh` automates all of the above:

```bash
scripts/verify.sh JQ_ARGS_YAML INPUT OUTPUT [--expected N] [--direct "FILTER"] [--cmd PATH]
#   --expected N   assert the array has exactly N rows
#   --direct F     also byte-compare the yaml-wrapped run against a direct
#                  single-quoted run of F (same args from the yaml)
#   --cmd PATH     check cmd.sh: exists, non-empty, EXECUTABLE, and
#                  references the output path + reconstruction line
```

One-shot invocation used in practice — keep the filter in a scratch file
while developing, then hand it to `--direct` via `$(cat ...)` so it is never
retyped (the value is passed verbatim, same bytes as the yaml's filter):

```bash
bash /skill/scripts/verify.sh /app/jq_args.yaml /app/users.json \
  /app/verified_admin_contacts.json --expected 203 --cmd /app/cmd.sh \
  --direct "$(cat /tmp/filter.txt)"
```

Run steps 0–4 unconditionally (keys check; per-item args contract —
every item must start with `-`; escape audit; reconstruction; output sanity
with the ALWAYS-ON indent check, which reads `--indent N` from args when
present and otherwise asserts jq's default 2 spaces, skipped only for
compact or single-line output); `--direct` adds the byte-cmp mode;
`--cmd` turns on the mode-bit/content check for the saved command file.
The script exits nonzero with a distinguishable `FAIL:` line on any failure.

- **Reaching the assets**: the task container may mount the skill package
  read-only at `/skill` (root = the family dir — check `ls /skill/scripts`).
  Host-workspace paths are NOT visible inside the container (`bash
  /home/.../scripts/verify.sh` fails with exit 127 — seen in the iteration-1
  fresh run, which then had to hand-copy the script). Invoke
  `bash /skill/scripts/verify.sh ...`, copy the script to `/app` first, or
  fall back to the inline commands above.

## 6. Verification methodology (adaptive, per variant)

1. **Subpopulation arithmetic**: compute N(source rows passing the positive
   predicate) and N(passing positive but excluded by each exclusion rule
   — print these ids for hand inspection); assert
   `output length == N(positive) − N(excluded)`. v01: 230 active+privileged
   − 27 self-blocked = 203 rows [v01].
2. **Program-wide `all` predicates** over the output: every normalized list is
   sorted+unique; counts equal list lengths; "first item" == `roles[0]`;
   string-format fields match `test` regexes; derived fields equal what the
   normalization rule prescribes; default values only where the source was
   missing/blank (re-join with source when needed). [v01]
3. **Trap-record spot checks**: pick raw records exercising each trap
   (whitespace-padded values, duplicates that collapse after normalization,
   uppercase inputs, blank/missing fields, self-excluding records) and print
   their transformed output. [v01]
4. **Cross-set checks inside jq** (`--slurpfile` joins), not `comm`/`sort` on
   extracted text — the text-extraction route silently misbehaves [T, v01
   detour]. Remember `.[]` before a top-level `select` on an array ("Cannot
   index array with string" error).
5. For a **new variation** (any spec axis): apply procedure 1 with the new
   predicates; for new normalizations, run the rule standalone
   (`INPUT | <rule>`) and assert `all(. == output field)` record-by-record;
   for new aggregation, assert sum-of-parts identities; for new ordering,
   scan adjacent rows programmatically for key-direction violations as in the
   v01 sort check.

### Grader test surface (from evaluation feedback, iterations 1–2)

Observed [G] — test names plus pass/fail outcomes only: output exists;
output is valid JSON; output matches the expected transformation
"exactly"; schema/field shapes; normalization of dates/contact/phone;
roles normalized-deduped-sorted plus the privileged gate; excluded users
absent; final sort direction; 2-space pretty print; cmd.sh replay works;
jq_args.yaml valid and reconstructs the command (the per-item
`startswith("-")` assertion is directly observed from the iteration-1
failure); the saved command AND the yaml-reconstructed command handle
adversarial input variants; input hash unchanged (the input file must stay
unmodified).

Inferred [E] — the comparison mechanism inside "..._exactly" is
**unobserved**: it may compare raw bytes or parsed structure. Emit canonical
field order and spec-literal formatting/types regardless — that satisfies
both possibilities without over-fitting (do NOT treat an equivalent key
reordering as a contract violation worth burning calls on). If a future
feedback round shows field-order-tolerant output, downgrade "byte-exact"
to "structural".

Takeaways: **output fidelity matters** (`..._exactly` + pretty-print tests
exist), **artifacts matter** (cmd.sh + yaml contract), **robustness
matters** (adversarial variants), **input integrity matters** (hash check).

## 7. Gotchas and version facts

- `args` items must each start with `-` [G]: `["--indent", "2"]` fails the
  grader on item `'2'` (iteration-1's only failure); use one self-contained
  item `["--indent 2"]`, or `args: []` (jq default is already 2-space).
  `--indent=2` → jq 1.6 "Unknown option".
- Inside `any(gen; cond)`, `map(cond)`, or generator conditions, `.` is
  rebound to each element — outer-record fields are invisible inside the
  condition unless bound first with `as $x`. Iteration-2 probe bug:
  `any(.blocked[]; . == $rec.d)` reported 0 self-blocked when there were
  27; bind the outer value before the generator (`$d as ... | any($blocked[]; . == $d)`)
  and distrust probe results that contradict known subpopulation counts —
  re-derive with an alternative formulation. [G, iteration-2 trajectory]
- Over-escaped `\\\\s` in YAML → silent non-match → records vanish; output
  still looks fine. (§P5)
- `unique`/sort before normalization keeps noise-distinct values. (§P2)
- `contains` is substring semantics — not equality. (§P2)
- `//` does not replace `""`. (§P3)
- `sub` on a number crashes — type-guard non-string scalars. (§P3)
- `sort_by` has no descending key; codepoint-negation breaks prefix pairs. (§P4)
- jq 1.6 (this environment): `--indent n` OK; `IN(gen)`, `any(gen; cond)`,
  `capture`, `try/catch` OK; optional chaining `.?` is jq 1.7+.
- EDA-certified seed shapes that hidden variants may break [v01 → E]: every
  email has exactly one `@` (family-general: `split("@")` and take
  `[1:] | join("@")` or guard), `last_login` always ISO with `T`, phones only
  `null`/string, roles always an array, blocked lists always present. Write
  guards (`// []`, `// ""`, type checks) instead of trusting the seed.
- `yq` here prints `0.0.0` for `--version` (Python yq, version unset) — not a
  blocker; the reconstruction line is the contract.

## 8. Future verification procedure for extrapolated axes [E]

Each spec-declared axis not exercised in v01 has a concrete check: (selection)
recompute arithmetic with the new predicates and hand-inspect boundary
records; (reshaping) assert the output schema key-for-key and validate each
derived field against the rule applied standalone; (normalization) the
standalone-vs-embedded `all` equality above; (aggregation) sum-of-parts
identities and cross-check with `group_by` on the source. Run these before
declaring a variant solved; one v01 success does not certify an axis.