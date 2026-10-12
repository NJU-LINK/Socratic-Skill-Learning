# jq idioms for data-processing tasks

Mechanism-focused catalogue. Each idiom: what it does, why it is shaped that
way, and its failure mode. All exercised on v01 data unless marked
[extrapolated] (spec-declared axis, mechanism reasoned, verify on new input).

## String normalization

### trim — jq has NO built-in trim
```jq
def trim: sub("^[[:space:]]+"; "") | sub("[[:space:]]+$"; "");
```
Mechanism: Oniguruma regex, both ends, POSIX class `[[:space:]]` covers space,
tab, newline. Failure mode: applying `sub` to `null` or a number errors —
`tostring` first when the type may vary.

### Role-style normalization = trim + lowercase
```jq
def norm: trim | ascii_downcase;
```
Order matters: trim first, then lowercase (either order works for these two,
but trim-then-lower is the contract's stated order — mirror the instruction).
`ascii_downcase` (not `upcase`). Use `ascii_downcase` rather than `lowercase`
for determinism across locales.

### Domain extraction — first `@` only
```jq
.email | sub("^[^@]*@"; "") | ascii_downcase
```
Mechanism: strips everything up to and including the *first* `@`, so emails
with multiple `@` keep the part after the first `@`. Then lowercase.
Failure mode: `split("@")[1]` errors on a string without `@`; the `sub` form
is safer. Guard with `// ""` if the contract might contain malformed emails.

### ISO 8601 → YYYY-MM-DD
```jq
.last_login | split("T")[0]
```
Mechanism: survives microseconds (`2026-03-16T05:01:40.829540Z`) and
timezone suffixes because everything after `T` is discarded. Failure mode:
input without `T` (bare date) still works; input that is not a string errors.

### Phone / free-text with fallback: missing, null, blank → default
```jq
(((.phone // "") | tostring | trim) as $p | if $p == "" then "unknown" else $p end)
```
Mechanism: `// ""` collapses missing and `null`; `tostring` makes a numeric
phone safe (`123` → `"123"`); `trim` collapses whitespace-only to `""`; the
`if` maps empty to the default. Never apply `sub`/`trim` to an untostringed
value. [v01 evidence: 83/500 records have `phone: null`; check passed.]

### Optional / missing arrays
```jq
(.roles // [])          # [] when missing OR null
[.x[]?]                 # iterates if array exists, else empty — safe streaming
```
`//` also fires on `false`, `0`, `""` (they are "falsey" in jq's `//`). Use
an explicit `if` when `false` is a legitimate value.

## jq scoping pitfall: `.` changes meaning inside callbacks

Inside `index(f)`, `any(f)`, `all(f)`, `map(f)`, the input of `f` is the
array element, NOT the surrounding record. `(.blocked | index(.email))`
fails with `Cannot index array with string "email"` because `.email` is
evaluated against the blocked array. Fix: bind record fields to variables
before the callback:
```jq
($u.blocked_domains // []) as $bl | ($u.email | sub("^[^@]*@"; "")) as $d | ... ($bl | index($d) | not)
```
Same pitfall inside `all(.[]; E)` in verification scripts: bind first
(`.account_summary as $s | ... $s.roles[0] ...`). [v01 evidence: both my
verification invariant and an independent cross-check filter hit this
exact error before binding.]

## Missing-field null semantics — the vacuous-verification trap

In jq, indexing a missing field yields `null` **without error**. This makes
the failure signal of inherited verification checks asymmetric: equality
and sort-order invariants degrade into vacuous passes, while string
operations on the same nulls fail loudly. Probes (jq 1.6, exact outputs):

```
# A: equality invariant on a schema it was never written for — passes VACUOUSLY
$ printf '[{"a":1},{"b":2}]' | jq -e '[.[].email_domain] == ([.[].email_domain] | sort)
# -> true, exit 0  — nothing was checked; [null,null] == [null,null]

# B: substring invariant on the same data — fails LOUDLY with a type error
$ printf '[{"a":1},{"b":2}]' | jq -e 'all(.[]; (.phone | sub("^[[:space:]]+"; "")) == .phone)'
# -> jq: error (at <stdin>:0): null (null) cannot be matched, as it is not a string; exit 5

# C: uniform-key-set check on legitimately non-uniform output — correctly fails
$ printf '[{"a":1},{"b":2}]' | jq -e '(map(keys) | unique | length) == 1'
# -> false, exit 1  — the check is contract-true for v01 (grader asserts schema
#    uniformity) but NOT family-true: a field_derivation variant may legitimately
#    emit heterogeneous records. Uniform keys also do NOT make field invariants
#    sound: '[{"x":1},{"x":2}]' passes C while every email_domain check stays
#    vacuous (A).
```

Consequence for verification tools: any reusable verifier must split
**contract machinery** (rebuild, byte identity, replay, textual predicates)
from **task-shaped literals/predicates** (field names, key names,
uniformity). The second half must be re-derived from each task's instruction
— an inherited check on the wrong field name does not fail, it lies.
(verify.sh encodes this split behind a loud `TASK-SHAPED CHECKS` marker.)

## Selection

```jq
select(cond1 and cond2 and cond3)
($nr | any(. == "admin" or . == "owner"))   # at-least-one inclusion
($blocked | index($domain) | not)           # not-contained exclusion
select(.status == "active")                 # scalar equality
```
Mechanism: `any`/`all` take a generator or a boolean-producing filter;
`index(x)` returns index or `null`, so `| not` turns "found" into "excluded".
Always select on *derived* values (normalized roles, normalized blocked
domains, normalized domain), never on raw text with case/space noise.
[extrapolated] Selection interacting with aggregation: compute the aggregate,
bind with `as`, then `select` against it — do not recompute in the predicate.

## Shaping

```jq
{ user_id: $u.id, ... }                       # rename
"\($u.username) <\($u.email)>"               # combine fields into one
account_summary: { role_count: ..., roles: ... }  # nested objects
```
Mechanism: object construction copies the *current* `.` by default
(`{a: .a}`) — use explicit `$u` bindings to avoid accidental capture of a
changed `.`. String interpolation `\(...)` embeds the string form of any
value. Nested output arrays: wrap with `[ ... ]` in the pipeline;
`[ .[] | {...} ]` transforms every input record into one output record and is
the standard "map records" idiom.

## Ordering

### Ascending
```jq
sort_by(.email_domain)
sort_by(.a, .b)          # multi-key, all ascending
```

### Mixed direction — ascending X, descending Y
```jq
sort_by(.email_domain) | group_by(.email_domain) | map(sort_by(.username) | reverse) | add
```
Mechanism: `sort_by` is ascending-only; a plain `reverse` after a
multi-key `sort_by` flips *both* keys. `group_by(f)` sorts internally by
the key (groups in ascending key order; within each group, elements keep
their relative input order — the sort is stable in jq 1.6), so the leading
`sort_by(.email_domain)` is **not a precondition**: it is redundant for
group order here because group content is re-derived inside `map(...)`.
Keep a leading `sort_by` only when you deliberately use stability — the
pre-sort fixes the baseline input order that `group_by` preserves within
groups.

Probed evidence (jq 1.6, one-liners):
```
$ jq -nc '[3,1,2,1] | group_by(.)'          # -> [[1,1],[2],[3]]   no pre-sort; groups ascend
$ jq -nc '[{"d":"b","n":1},{"d":"a","n":2},{"d":"b","n":3}] | group_by(.d)'
# -> [[{"d":"a","n":2}],[{"d":"b","n":1},{"d":"b","n":3}]]
#    b-group keeps input order (n=1 before n=3): stable within group
$ jq -nc '[{"d":"c","n":3},{"d":"a","n":1},{"d":"c","n":2},{"d":"b","n":4}] | group_by(.d)'
# -> a-group, b-group, c-group with c-group in input order (3,2)
```

### Descending PRIMARY key, ascending secondary
```jq
group_by(.k) | reverse | map(sort_by(.j)) | add
```
Mechanism: `group_by` already produces ascending groups; reverse the
**group list**, not the contents, to get descending primary order, then
sort within each group. Counterexample proving the naive form fails (the
reverse is discarded for group order and leaks into within-group order
via stability):
```
$ jq -nc '[{"k":"a","j":2},{"k":"b","j":1},{"k":"a","j":3}] | sort_by(.k) | reverse | group_by(.k)'
# -> [[{"k":"a","j":3},{"k":"a","j":2}],[{"k":"b","j":1}]]   groups still a,b! and a-group got scrambled
$ jq -nc '[{"k":"a","j":2},{"k":"b","j":1},{"k":"a","j":3}] | group_by(.k) | reverse | map(sort_by(.j)) | add'
# -> [{"k":"b","j":1},{"k":"a","j":2},{"k":"a","j":3}]          correct: b first, j ascending in-group
```
[extrapolated] More complex composite ordering: decorate → sort → undecorate
at the COLLECTION level: `map([.a, (.b|ascii_downcase), .]) | sort_by(.[0], .[1]) | map(.[2])`.
The `sort_by` must follow the wrapping `map` on the top-level pipe — inside
the per-record `map` it would sort a one-element array and do nothing
(SKILL.md v1 carried exactly that bug). For a descending inner key, negate
the deco element with `-` — **numeric keys only**, and null-guard first
(`(.n // 0)` as the deco element; arithmetic on `null` errors).

## Cross-record / collection primitives (aggregation axis)

| primitive | meaning | failure mode |
|---|---|---|
| `length` | string length, array length, object key count | on `null` errors — guard |
| `add` | sum array of numbers / concatenate strings | wrong on objects; empty array → `null` (use `// 0`) |
| `unique` | dedupe + sort ascending (strings, numbers) | — |
| `unique_by(.k)` | dedupe by key, keeps first occurrence [extrapolated] | input order matters |
| `group_by(.k)` | groups by key: internal sort — ascending group order, stable within groups (input order preserved); no pre-sort needed | group order is ascending, period; `reverse` before it is discarded (and leaks into in-group order via stability) |
| `sort` / `sort_by(.k)` | ascending sort | no descending form |
| `flatten` | flatten nested arrays one level (or `flatten(N)`) [extrapolated] | — |
| `map(f)` / `map_values(f)` | apply to each element / each value | — |
| `reduce .[] as $x (init; update)` | manual fold [extrapolated] | update must consume $x |
| `[.[] | select(...)]` | subset collection | — |

Collection-level summary pattern:
```jq
[ .[] | .status ] | group_by(.) | map({status: .[0], count: length})
```
No pre-sort needed: `group_by` sorts internally, so the summary comes out
in ascending status order with counts. Descending summaries: reverse the
group list (`group_by(.) | reverse | map(...)`).

Two-pass workflow (per-record transformation + cross-record aggregation in
one jq program): either repeat `[ .[] | ... ]` twice, or bind the collection
first: `[ .[] | ... ] as $all | $all | ...pipeline using $all...`.

## Self-contained filter rule

Do not rely on `--arg` / `--argjson` / `-f file.jq` / environment. Put
everything in the `filter` string: local `def`s, literals for constants
(`"admin"`, `"owner"`), no external files. Rationale: the evaluator rebuilds
from `jq_args.yaml` whose `args: []` word-splits unquoted tokens — anything
with grouped flags re-quotes badly. `args: []` is the only robust choice;
the filter string carries all logic.

## jq flags you will (not) need

- No flag for 2-space indent: jq default pretty mode is exactly that.
- Never `-c` (compact) unless the contract demands single-line output.
- `-r` only needed for raw string output; object/array output is fine raw.
- `-S` (sort keys) only if the contract demands alphabetical object keys —
  byte-diffing against a reference without `-S` will then fail, so check the
  contract wording before adding it.