---
name: jq-data-processing
description: >-
  Solve jq-only JSON data-transformation tasks in the jq-data-processing family:
  read a JSON input file, apply record selection and ordering, derive and reshape
  output fields, normalize scalar values, and (optionally) aggregate across
  records using a single jq filter; then emit the pretty-printed JSON report plus
  the cmd.sh / jq_args.yaml artifacts expected by the task harness. Covers
  multi-condition predicates, include/exclude logic, multi-key and descending
  sorts, deep/optional field access, nested output objects, string cleanup,
  date/number/boolean conversions, fallback defaults, dedup, grouping and
  collection-level summaries.
---

# jq-data-processing

Turn a JSON file into a transformed JSON report using **jq only** (never Python,
Ruby, or other languages). This skill covers the whole family: selection and
ordering logic, field derivation and reshaping, scalar value normalization, and
aggregation/collection operations — any combination of these may appear in a
single task, so build one filter that does all of it in a pipeline.

## 1. Task shape and artifacts (family invariants — grounded by v01)

Every task in this family (v01 anchor: `train/v01/task.yaml`) follows the same
interface; always re-read the current task file, because exact filenames, keys
and rules are the ground truth:

- **Input**: a JSON file, conventionally `/app/<input>.json` (v01:
  `/app/users.json` — an array of account records).
- **Output**: a JSON file, conventionally `/app/<output>.json` (v01:
  `/app/verified_admin_contacts.json`), formatted as pretty-printed JSON with
  **2-space indentation**. jq 1.6/1.7 already default to 2-space indent, so no
  flag is needed; do NOT use `-c`/`-r` for the report (they change the format).
- **`/app/cmd.sh`**: the exact jq command you executed, **including the output
  redirection** (`> /app/<output>.json`), with ONE hard formatting
  constraint: the file's first non-whitespace content must literally be
  `jq ` — NO `#!/bin/bash` shebang, NO comment or blank first line. The
  harness reads the file and asserts it starts with `jq ` (observed in v01's
  test suite: `test_jq_command_file_and_replay_work` failed only because a
  `#!/bin/bash` first line was present; the replay itself would have run
  fine). Write it as a single command line, e.g. with
  `printf 'jq ...\n' > /app/cmd.sh` or a heredoc WITHOUT a shebang line,
  then verify `head -1 /app/cmd.sh` starts with `jq `.
- **`/app/jq_args.yaml`**: all jq arguments except the fixed input/output files,
  with exactly two keys:
  - `filter`: a string containing the jq filter expression
  - `args`: a list of strings; each item is one complete jq argument (flag +
    value together, e.g. `--arg name alice`); empty list `[]` when no flags.
- The harness reconstructs and runs:
  `jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/<input> > /app/<output>`
  Make `/app/cmd.sh` contain exactly this reconstructed form (with the real
  paths), so the artifacts are self-consistent and re-runnable.

Store the filter in YAML as a **block scalar** (`filter: |-`), which preserves
quotes and backslashes verbatim; `yq -r '.filter'` then yields exactly the jq
expression (verified with yq 3.1.0 + jq 1.6 in the v01 environment; other yq
flavors — Python-kislyuk or Go-mikefarah — accept the same reconstruction, so
always prove the round trip locally with the exact harness form). Empty
`args: []` produces no flags, which is correct when the task needs none.

- **Adapt to the ACTUAL task text**: filenames, artifact requirements, keys
  and semantics come from the current `task.yaml`, not from v01's example. The
  v01 interface above is the anchor, but a variant may rename the input/output
  files, use different artifact instructions, or change the schema. Two
  cheap adaptation checks before drafting any filter:
  - Input shape: `jq 'type' IN` — if it is NOT a top-level array (v01 shape)
    but an object wrapper (e.g. `{"users": [...]}` or a single record),
    iterate the right path: `[.users[] | ...]`. Never assume; look.
  - Output shape: the report is the ONE JSON value your filter emits — array,
    object, or a nested combination (§2.2/§2.4). jq pretty-prints any single
    value with the default 2-space indent.
- **Replay robustness is tested by the family's harness**: v01's tests re-run
  the saved `cmd.sh` and the yaml-reconstructed command against adversarial
  input variants (missing keys, nulls, extra whitespace, case changes). The
  saved filter must therefore NEVER crash on plausible perturbations and must
  apply the task's normalization rules identically on them — write it
  defensively from the start (§5 step 7), using `// ""`, `[]?`, and
  type-safe guards instead of assuming clean data.
- **Never modify the input file** — write only to the output path (the
  harness checks the input hash).

## 2. The four variation axes and how to handle them

### 2.1 selection_and_ordering_logic
- **Single equality** (v01): `select(.status == "active")`.
- **Multi-condition predicates**: chain `select(...)` calls or use one
  `select(A and B)`. Test each condition on **normalized** values when the task
  says normalization happens before checking (v01 normalizes roles and domains
  before ALL comparisons).
- **Inclusion (whitelist)**: `select(any(.tags[]; . == "x" or . == "y"))`.
- **Exclusion (blacklist)**: `select((.blocked | index($v)) == null)` — bind the
  searched value to a variable first (see Pitfall 2), or
  `select(any(.blocked[]; . == $v) | not)`.
- **Selection on derived values / intermediate stages**: compute scratch fields
  first (`. _x = ...`), then `select(...)` on them; this keeps one pipeline and
  reuses the derived values in the output (v01 pattern:
  `._domain`, `._roles`, `._blocked` computed before the selects).
- **Ordering** (multi-key, mixed directions — EVERY row below verified in-container on jq 1.6):
  - **Preferred: one `sort_by` with direction-encoded keys** — no stability dependence, and ties stay in input order (same as stable graders). Define a descending string key at the top of the filter:
    ```jq
    def desc: explode | map(-.) + [1];   # sortable key for DESCENDING string order
    ```
    Mechanism (verified): `explode | map(-.)` reverses non-prefix comparisons; appending `[1]` (any value > 0, since every negated codepoint is ≤ 0) makes the LONGER of two prefix-related strings compare smaller — exactly the reversal the bare-prefix rule refused to give. Each key's direction is local and composes naturally in one call:
    - domain ASC, username DESC (v01 order): `sort_by(.email_domain, (.username | desc))`
    - domain DESC, username ASC: `sort_by((.email_domain | desc), .username)`
    - numeric keys: `.score` / `-.score` in the same list (e.g. `sort_by(.d, -(.n))`).
    Guard against missing values before exploding: `((.username // "") | desc)` (`null | explode` errors).
  - **Stable two-pass recipes** (alternative style). Master principle: **the last operation decides**. A stable `sort_by(primary)` preserves the secondary order you built; a trailing `reverse` flips EVERYTHING (secondary included), so set lower-priority keys in the opposite of their final direction first. For k1 primary, k2 secondary:

    | k1 | k2 | filter |
    |---|---|---|
    | asc | asc | `sort_by(.k1, .k2)` |
    | asc | desc | `sort_by(.k2) \| reverse \| sort_by(.k1)` (v01) |
    | desc | asc | `sort_by(.k2) \| reverse \| sort_by(.k1) \| reverse` |
    | desc | desc | `sort_by(.k1, .k2) \| reverse` |

    General N keys (k1 most significant, directions d_i ∈ {asc=0, desc=1}): reverse-flags r_1 = d_1, r_i = d_i XOR (r_1 XOR … XOR r_{i-1}); apply passes least→most significant, appending `| reverse` iff r_i = 1. Verified for (desc,asc,desc): `sort_by(.k3) | reverse | sort_by(.k2) | reverse | sort_by(.k1) | reverse`. The naive "apply desc first" attempt — `sort_by(.d) | reverse | sort_by(.u)` for desc-primary/asc-secondary — is SILENTLY WRONG (u becomes primary; d broken inside u groups; no jq error).
  - **Tie order nuance** (verified): every `reverse` flips full-tie blocks (records equal on ALL sort keys); an odd number of reverses therefore puts tie blocks in reversed input order, while stable graders (jq, Python `sorted`) preserve input order. If the task declares no tie-break, prefer the encoded single `sort_by` (zero reverses) and do NOT invent a tertiary key to guess the grader's tie-break.
  - **Null/missing keys** (verified): bare `sort_by(.k)` places `null` and missing keys FIRST. "Missing/null last": `sort_by((.k == null), .k)`. To send only truly-missing keys last (present-null sorts with values): `sort_by((has("k") | not), .k)`.
  - Always re-read the sort wording ("then by …", asc/desc per key) and apply it in the declared order; when no tie-break is declared, do not guess one.

### 2.2 field_derivation_and_reshaping
- **Rename**: `user_id: .id`.
- **Keep fields**: `username: .username` (or bare shorthand `username`).
- **Derive from one field**: e.g. domain from email —
  `((.email // "") | split("@")[-1] | ascii_downcase)`.
- **Combine several source fields into one output field**:
  `.username + " <" + .email + ">"` or interpolation `"\(.username) <\(.email)>"`.
- **Nested output objects**: build them inline —
  `account_summary: { role_count: ..., primary_role: ..., roles: ... }`.
- **Deep/optional access**: `.a.b.c` for required paths; `.a.b.c?` or
  `.a?.b?.c` so missing/null intermediate objects yield `null` instead of an
  error; empty arrays from iterators: `[.maybe_missing[]? | ...]` → `[]`.
- **Structure that diverges from input**: collect-then-rebuild with
  `[ .[] | {...} ] | ...`; transpose via `to_entries`/`from_entries`; flatten
  nested arrays with `flatten`; emit nested arrays of objects by mapping inside
  a `[...]` constructor.
- **Substantially different output structures** (verified on jq 1.6):
  - object keyed by a field: `map({key: (.id | tostring), value: .}) | from_entries`
  - grouped object: `group_by(.d) | map({key: .[0].d, value: length}) | from_entries`
  - wrapper report: `{records: [ .[] | {...} ], total: length, ...}`
  - reshape via `to_entries` / `from_entries` (array of `{key,value}` ↔ object)
- Object key order in the output follows the order written in the object
  literal — write keys in the order the task lists them.

### 2.3 value_normalization
- **Trim + lowercase BEFORE any comparison/dedup/sort/selection** (central v01
  rule): `gsub("^\\s+|\\s+$"; "") | ascii_downcase` (both `\s` and POSIX
  `[[:space:]]` work in jq 1.6 — verified).
- **Extract part of a structured string**: `split("T")[0]` for date part of an
  ISO 8601 timestamp (or `[0:10]`); `split("@")[-1]` for domain; `capture(...)`
  for regex groups.
- **String cleanup**: `gsub`/`sub` with regex; `trim` is NOT a jq builtin —
  use the gsub idiom above.
- **Type-safe stringification** (for replay robustness and numeric/boolean
  variants): `(.x | if . == null then "" else tostring end)` turns
  missing/null → `""`, numbers → `"42"`, booleans → `"false"`. Do NOT use
  the shorthand `(.x // "")` for this: `//` ALSO falls back on `false`
  (verified: `false // ""` → `""`), which would silently destroy a
  meaningful `false` value.
- **Numeric coercion**: `tonumber?` (safe), `.+0`, `floor/round`; beware
  `tonumber` erroring on non-numeric input — prefer `tonumber?` + `// default`.
- **Boolean derivation**: `any(.roles[]; . == "admin")` etc.
- **Fallback defaults / null propagation**: `//` alternative operator returns
  the right side when the left is `false`, `null`, or empty:
  `(.phone // "")` for missing→empty, `(x // "unknown")` for missing→default.
  `//` also works after `select`-style pipelines (`... | select(. != "") // "unknown"`
  returns the fallback when the left stream is empty — verified), but an
  explicit `if . == "" then "unknown" else . end` is clearer.
- The task text dictates the null policy (e.g. v01: phone → `"unknown"` when
  missing **or blank**; roles → `null` primary when none remain). Implement
  exactly what the text says.

### 2.4 aggregation_and_collection_operations
- **Per-record collection work** (v01): count `| length`, dedup+sort `| unique`
  (unique both sorts and dedups — verified), first item `.[0] // null`.
- **Cross-record grouping**: `group_by(.k) | map({k: .[0].k, n: length, ...})`.
- **Subset aggregation / collection-level summaries**: `[.[] | select(...) | .x]
  | add`, `length`, `max_by(.x)`, `min_by(.x)`, `unique_by(.k)`, `group_by` +
  `reduce`.
- **Dedup values across records**: `[.[].k] | unique`.
- **Flatten/rebuild arrays**: `flatten`, `[.[] | ...]`, `map(...)`.
- **Combine per-record transformation with cross-record aggregation in one
  filter**: do per-record work inside `[ .[] | ... ]`, then pipe the resulting
  array into `group_by(...)`/`sort_by(...)`/summaries — a single jq program can
  output both the record list and aggregate fields (e.g. wrap in
  `{records: ..., summary: ...}`) when the task asks for it.
- **Worked cross-record patterns** (verified on jq 1.6):
  - counts per group: `group_by(.d) | map({d: .[0].d, count: length})`
  - group summary with subset aggregation:
    `group_by(.d) | map({d: .[0].d, total: ([.[].n] | add), count: length})`
  - subset stats on selected records: `[ .[] | select(<pred>) | .n ] | add` / `length` / `max` / `min`
  - per-record + cross-record in one value:
    `{total_users: length, per_user: map({u, count: (.r | length)})}`

**Single-workflow mechanics — cross-record + per-record in ONE filter** (all
probes verified in-container on jq 1.6; version caveats noted):

- **Streams are single-use, so materialize once and reuse via `as`**: a
  pipeline consumes its input once — `[...] | A | B` gives B only A's
  output, never the original array. `EXPR as $v | REST` freezes EXPR's value
  and passes the input through (Pitfall 12), which is the pattern every
  records-plus-aggregates task needs:
  - (a) Record list AND aggregates from the SAME filtered set — collect
    once, bind, then read the variable twice:
    ```jq
    ([.[] | select(<pred>) | <transform>]) as $kept
    | { records: $kept,
        summary: { n: ($kept | length),
                   avg: (if ($kept | length) == 0 then 0
                         else ($kept | map(.x) | add) / ($kept | length) end) } }
    ```
  - (b) Decorate every record with a collection-level value — `$total` is
    computed against the whole input, then `map` runs on the ORIGINAL input:
    `([.[] | .x] | add) as $total | map(. + {pct: (.x / $total)})`.
    Per-group decoration: `group_by(.g) | map( (map(.x) | add) as $t | map(. + {pct: (.x / $t)}) )`.
  - (c) Grouped summaries: `group_by(.g) | map({g: .[0].g, n: length, total: (map(.x) | add)})`.
    Three `group_by` behaviors decide correctness (all verified): groups come
    out SORTED ASCENDING by key, so "order groups by count/total" needs a
    second `sort_by(length) | reverse`; a composite key must be ONE array
    key (`group_by([.a, .b])`); keys are compared WITHOUT normalization, and
    mixed-type keys do NOT error in jq 1.6 — they sort by jq's total type
    order (null < false < true < number < string < array < object), which is
    never the intended semantics — so normalize/coerce the key to one type
    BEFORE grouping, exactly like the selection discipline.
- **Empty sets** (verified jq 1.6): `[] | add` → `null`; `[] | min` → `null`;
  `[] | max` → `null`; `[] | min_by(.x)` → `null`; `[] | max_by(.x)` →
  `null` (keys survive holding `null` on this build; other jq builds have
  been observed to emit NOTHING for `_by` on empty — never rely on which;
  guard always). `null` breaks most arithmetic: `null + n` → `n`, but
  `null - n`, `null * n`, `null / n` are ERRORS, and `[] | add / length`
  errors with "null (null) and number (0) cannot be divided". THE silent
  failure is an empty GENERATOR (`[1,2][] | select(. > 5)`, or a subset
  filter that selects nothing flowing into a per-record consumer): it
  yields NO value, so a field expression silently vanishes the key and a
  record construct silently drops the whole record (exit 0, no error).
  Guard with `//` — `(xs | add // 0)`, `(xs | min_by(.x) // 0)` — which
  catches both `null` and empty (`empty // 0` → `0`), and guard denominators
  explicitly: `if length == 0 then 0 else add / length end`. Also `.[]` on a
  `null` input ERRORS ("Cannot iterate over null") — iterate `[]?` or
  materialize first.
- **Sort placement belongs to the record level the task names**: the §3.1
  template's final `sort_by` assumes the last stage emits records. "Sort the
  final array" → records, final stage (template comment is then right);
  "order groups by total desc" → sort AFTER `group_by`; "records inside
  each group" → sort INSIDE each group — but `sort_by` needs an ARRAY
  input, so collect the group's transformed records first
  (`group_by(.g) | map( ([.[] | <transform>] | sort_by(<key>)) | <group shape> )`);
  piping a raw group stream into `sort_by` errors ("Cannot index number with
  string ..."). Group ordering after, per the task wording. Re-read which
  level "final" names before placing any `sort_by`.

## 3. Working filter skeletons

### 3.1 Generic pipeline template (fill in per task)

Five stages, one filter, one output value — every family task maps onto this:

```jq
def desc: explode | map(-.) + [1];           # descending string key (§2.1)
[ .[]                                        # .<wrapper>[] if input is object-wrapped (§1)
  | . as $r                                  # FREEZE the record FIRST (Pitfall 12): $r.* survives any pipe
  | ._f1 = <derive + normalize from source>  # bind ALL derived values while `.` is still the record
  | ._f2 = ...                               # (scratch fields keep `.` the record; `(...) as $x` also fine)
  | select(<predicate on $r / scratch fields>)    # selection: equality / whitelist / blacklist
  | { <out_key>: <expr>, ... }               # rename / passthrough / derive / nest (§2.2)
]                                            # NEVER pipe a field extractor (`| .field`) into this chain:
                                             # it rebinds `.` and later `.field` reads fail (Pitfall 12)
| <cross-record aggregation if required>     # group_by / summaries (§2.4): MATERIALIZE once with
                                             # (...) as $v — streams are single-use (one consumer only)
| <sort_by with per-key direction>           # string desc: (key | desc); numeric desc: -(key); rest asc
```

### 3.2 v01 worked instance (verified end-to-end)

The v01 filter below is a concrete filling of the template; replace field
names, predicates, and output shape per the CURRENT task. It uses the encoded
one-pass sort (see §2.1); for an asc-primary/desc-secondary pair the two-pass
`sort_by(.username) | reverse | sort_by(.email_domain)` yields the same
verified result, but the encoded form is the safe default for any direction
mix:

```jq
def desc: explode | map(-.) + [1];       # sortable key: descending string order
[ .[]                                   # start: iterate input records
  | ._domain = ((.email // "") | split("@")[-1] | ascii_downcase)   # derived, normalized scratch fields
  | ._roles = ([.roles[]? | (gsub("^\\s+|\\s+$"; "") | ascii_downcase)] | unique)
  | ._blocked = [.blocked_domains[]? | (gsub("^\\s+|\\s+$"; "") | ascii_downcase)]
  | ._domain as $d                      # bind BEFORE using it inside array funcs (Pitfall 2)
  | select(.status == "active")         # selection predicates (normalized values)
  | select(any(._roles[]; . == "admin" or . == "owner"))   # note the [] on the array
  | select((._blocked | index($d)) == null)                # exclusion
  | {                                    # output record (key order as specified)
      user_id: .id,
      username: .username,
      email: .email,
      email_domain: ._domain,
      contact: (.username + " <" + .email + ">"),
      phone: ((.phone // "") | gsub("^\\s+|\\s+$"; "") | if . == "" then "unknown" else . end),
      last_login: ((.last_login // "") | split("T")[0]),
      account_summary: {
        role_count: (._roles | length),
        primary_role: (._roles[0] // null),
        roles: ._roles
      }
    }
] | sort_by(.email_domain, (.username | desc))   # domain asc, username desc (one pass)
```

The whole filter evaluates to ONE array value, so jq pretty-prints it with the
default 2-space indentation.

## 4. jq pitfalls (all verified experimentally in the v01 environment, jq 1.6)

1. **`any(array; cond)` tests the array as a single item** — it always yields
   false for `["a","admin"] | any(.; . == "admin")`. To test elements you MUST
   iterate: `any(.[]; cond)` / `any(.roles[]; cond)`. Same for `all`.
   (Instance of scoping rule 3, Pitfall 12: inside COND the `.` is the
   element, never the record.)
2. **`arr | index(expr)` evaluates `expr` against the whole array**, not the
   record: `._blocked | index(._domain)` errors with "Cannot index array with
   string". Bind first: `._domain as $d | ._blocked | index($d)`. (`index`
   returns `null`, not -1, when absent; `rindex` for last occurrence.)
   (Instance of scoping rule 1, Pitfall 12: EXPR runs against the array you
   piped in.)
3. **No string negation** — and the simple `explode | map(-.)` is NOT enough:
   `sort_by(-.username)` errors with "cannot be negated", and
   `sort_by(explode | map(-.))` does not reverse lexicographic order for
   prefix-related strings (verified: `["ab","a","b","aa"]` → `["b","a","ab","aa"]`,
   wrong — the prefix rule "shorter sorts first" survives negation). Two correct
   fixes: the encoded key `explode | map(-.) + [1]` (see §2.1), or the stable
   two-pass recipes from the §2.1 table. The two-pass asc-primary pattern
   (`sort_by(.k2) | reverse | sort_by(.k1)`) is only valid for ASC primary — for
   DESC primary use the double-reverse row.
4. **jq `sort_by` is stable** (verified) — this is what makes the two-pass
   pattern correct.
5. **`unique` sorts AND dedups** — ideal when the task wants a deduped sorted
   list; use `unique_by(.k)` for objects.
6. **`//` alternative**: falls back on `false`, `null`, or empty;
   `empty // "x"` → `"x"` (verified), so `... | select(...) // "unknown"` works,
   though an explicit `if` is clearer.
7. **Trimming**: jq has no `trim`; use `gsub("^\\s+|\\s+$"; "")` (works on
   jq 1.6; POSIX `[[:space:]]` also works). Normalize BEFORE comparing —
   comparing `" ADMIN "` to `"admin"` silently drops records otherwise.
8. **Missing fields**: `.roles[]?` yields nothing when `.roles` is missing, so
   `[.roles[]? | ...]` is `[]` (no crash); `.x?`/`.x.y?` suppress errors for
   one level; `(.x // "")` converts missing/null to empty string.
9. **`split("@")[-1]`** takes the last `@`-part (robust for any email form); negative indexing `.[-1]` works on both arrays and strings.
10. **Output format**: one filter output = one JSON value; keep the report as a
    single array/object so jq emits pretty JSON. `-r`/`-c` are for scalar/stream
    use and break the 2-space-indented format requirement.
11. **YAML round-trip**: write the filter with `|-` block scalar so `"` and `\`
    survive verbatim; verify by running the reconstructed command and diffing
    stdout with your direct run.
12. **Scoping: `.` is always the output of the immediately preceding stage**
    — the single model behind Pitfalls 1, 2 and this one (all verified
    in-container):
    - Rule 1 — `.` REBINDS on every pipe into an extractor/function/
      operator: in `A | B | C`, inside `B` `.` is A's output, inside `C` `.`
      is B's output. After `.email | ...`, `.` is the email STRING, so a
      later `.blocked_domains` fails with `Cannot index string with string
      "blocked_domains"` (reproduced exactly; the iteration-1 eval solver
      hit this in an ad-hoc count query: `... | .email | split("@")[-1]
      | ascii_downcase as $d | select(([.blocked_domains[]? | ...] |
      index($d)) == null)`).
    - Rule 2 — `EXPR as $v | REST` freezes EXPR's value in `$v` while REST's
      input remains what entered the binding: the scoping-safe way to carry
      derived values.
    - Rule 3 — `select(P)` and sort/array ops only filter/reorder: they pass
      the record through unchanged, which is why `select(A) | select(B)`
      keeps reading record fields — and why a chain breaks the instant you
      interleave an extractor. Inside `any(GEN; COND)` / `map(EXPR)` /
      `[...]`, the inner expression sees the ELEMENT: `any(.r[];
      .blocked == null)` fails with `Cannot index string with string
      "blocked"` (verified).
    Everything unifies: `arr | index(EXPR)` (Pitfall 2) evaluates EXPR
    against the array you piped in. Every `Cannot index [array|string] with
    string` is a SCOPING bug — ask "what is `.` at this point, and which
    value did I intend?", never "is the data broken?".
    **Construction discipline — "freeze first, then consume"**: immediately
    after the iterator `.[]` (while `.` is still the record) bind every
    derived value with `(...) as $x` or assign scratch fields (`. _x = ...`),
    then write all selects and the output object in terms of `$x` / `_x`. If
    you type `.field` after having piped into another extractor, you already
    committed the bug — stop and bind. Belt-and-suspenders variant: `. as $r`
    once at the top, then read `$r.field` everywhere; it survives accidental
    pipes (verified).

## 5. Procedure

1. **Extract the contract** from the task text: input path, output path,
   selection rules (statuses, whitelists, blacklists), normalization rules
   (trim/lowercase before what), per-field derivations and defaults, sort keys
   and directions, JSON formatting, artifact requirements (`cmd.sh`,
   `jq_args.yaml`).
2. **Inspect the data** before writing the filter:
   `jq 'type' IN` (array vs object wrapper — adapt iteration path);
   `jq 'length' IN`; field soup `jq '[.[] | keys | add] | unique'`;
   `jq -r '[.[].STATUS] | unique[]'`; counts of null/missing/whitespace values
   (`jq '[.[] | select(.phone == null)] | length'`); sample raw values
   (`jq '.[0]' IN`). Check `jq --version` and `yq --version`.
3. **Draft the filter in a file** (e.g. `/tmp/filter.jq`) and run
   `jq -f /tmp/filter.jq IN > /tmp/out1.json`; iterate stage by stage: compute
   scratch fields → selects → output object → sort. Add stage count checks
   (e.g. active=354 → +privileged=230 → −blocked=203 in v01).
4. **Cross-validate** with a second, differently-idiomed implementation
   (different variable style, `map(select(...))` vs `any`, interpolation vs
   `+`; for sorting, cross-check the encoded one-pass against the stable
   two-pass recipes). Canonicalize both with `jq -S .` and `diff`.
   Byte-identical canonical output = high confidence. Also verify count
   arithmetic on the source (candidates − excluded = final) and spot-check
   boundary records.
   Finally, **prove the sort** with the adjacent-pair invariant instead of
   eyeballing samples:
   `jq -e '[range(0; length-1) as $i | (.[$i].K1 < .[$i+1].K1 or (.[$i].K1 == .[$i+1].K1 and .[$i].K2 >= .[$i+1].K2))] | all' OUT.json`
   (flip `<`→`>` and `>=`→`<=` for a desc primary key; extend with `or`
   chains for more keys). This detects the silent wrong-direction failure
   that produces no jq error (verified: it passes correct outputs and fails
   the naive desc-primary/asc-secondary mistake).
   **Scoping guard**: the cross-check and any ad-hoc count queries die here
   first — a `Cannot index [array|string] with string` in ANY quick query is
   a scoping bug (you piped `.` away into an extractor), NOT a data bug
   (Pitfall 12). Bind the derived value with `(...) as $x` BEFORE the
   extractor and rerun. Note the §5 step-7 replay check cannot catch this
   class of bug: it replays only the finished (already-correct) filter on
   clean data.
5. **Write the artifacts**: `jq_args.yaml` (block-scalar `filter`, `args: []`
   or needed flags) and `cmd.sh` (exact reconstructed command with
   redirection). `cmd.sh` must START with `jq ` — no shebang, no comments,
   no blank line before it (the harness asserts `startswith("jq ")` on the
   file; v01's iteration-2 failed exactly this way after a `#!/bin/bash`
   line was added). Verify with `head -1 /app/cmd.sh`. Run `bash /app/cmd.sh`,
   then verify: valid JSON (`jq -e .`), `cmp` with the validated output,
   rerun for idempotence.
6. **Final review vs the text**: every output key named exactly as specified,
   every field rule implemented (trim/fallback/date), sort order correct,
   2-space indent, only jq used, input file untouched.
7. **Replay robustness** (the family's tests re-run your saved command on
   adversarial input variants — seen in v01's harness): create perturbed
   copies of the input (`/tmp/p1.json`, `/tmp/p2.json`, …): remove an
   optional key (`phone`, `last_login`, `roles`, `blocked_domains`), set a
   field to `null`, wrap values in extra whitespace, switch letter case.
   For each variant, clone `cmd.sh` with the variant path substituted for the
   input file AND a distinct output path for the report (e.g.
   `sed 's|/app/users.json|/tmp/p1.json|; s|/app/verified_admin_contacts.json|/tmp/out_p1.json|' /app/cmd.sh`),
   run it, and confirm: exit code 0 (no jq error like "Cannot
   index"/"cannot be gsubed"), and the output still follows the task's
   semantics (fallbacks appear, exclusions still work, normalization applies).
   ALWAYS substitute the output path too: a clone that only swaps the input
   still redirects into the real report file and clobbers it (v01's
   iteration-2 replay did exactly this — the solver's variant output
   overwrote `/app/verified_admin_contacts.json` until restored). After ALL
   replay testing, re-run `bash /app/cmd.sh` so the real output is guaranteed
   to be the final state.
   Fix any crash by adding `// ""` / `[]?` / type-safe guards (§2.3). The
   saved command itself must never crash on a plausible variant — that
   robustness, not the data's cleanliness, is what the replay tests check.

## 6. Failure modes and diagnosis

| Symptom | Cause / fix |
|---|---|
| `Cannot index array with string "x"` | `index(expr)` got a field-path arg; bind with `as $var` first (Pitfall 2). |
| `Cannot index string with string "field"` (or array) | An earlier `\| .field` / extractor piped `.` away, so the later `.field` is indexing a string/array — the SAME disease as the `index(expr)` row (Pitfall 12: `.` is always the previous stage's output). Freeze derived values with `(...) as $x` (or `. as $r` at the top) BEFORE piping into extractors, then write selects against `$x` / `$r.field`. |
| Too many/few records selected | Normalization missing before comparison (case/whitespace); `any(arr; c)` instead of `any(arr[]; c)`; exclusion logic inverted (`index($d) != null` vs `== null`). |
| Wrong order or "cannot be negated" | Descending string sort attempted via `-`; OR the asc-primary two-pass pattern applied when the PRIMARY key is descending — silent failure (`sort_by(.k1) | reverse | sort_by(.k2)` with k1 desc makes k2 the primary). Use the §2.1 table / encoded `desc` keys. Always PROVE the order with the adjacent-pair checker: `jq -e '[range(0; length-1) as $i | (.[$i].K1 < .[$i+1].K1 or (.[$i].K1 == .[$i+1].K1 and .[$i].K2 >= .[$i+1].K2))] | all' OUT.json` (flip `<`→`>` and `>=`→`<=` for desc primary); `-e` makes a violation exit nonzero. |
| Roles list unsorted or duplicated | Forgot `unique` or normalized after `unique` instead of before. |
| Blank/missing values leak through | Missing `// ""`/`// default`, or trim-before-blank-check omitted (v01 sanity check: 83 null + 42 whitespace-only phones in source; output has 39 `unknown` — recount with `jq '[.[] | select(.phone == "unknown")] | length'` against your own run, never guess). |
| Output on one line / wrong indent | Used `-c`/`-r`; remove flags; `args: []`. |
| Reconstructed command fails | YAML quoting/escaping of the filter; backslashes lost; verify with `yq -r '.filter'` output piped to `jq`. |
| cmd.sh replay test fails with a `startswith("jq ")` assertion | `cmd.sh` contains a `#!/bin/bash` shebang, comment, or blank first line. Rewrite it so the file begins with the `jq ...` line itself (no shebang) and re-verify `head -1 /app/cmd.sh`. |
| `last_login` wrong | Used `[0:10]` on missing value without `// ""`; prefer `(x // "") | split("T")[0]`. |
| Summary fields `null` / missing, or "null (null) and number (n) cannot be divided/subtracted/multiplied" | Subset is empty or partially filtered: array aggregates yield `null` (`add`/`min_by`) and empty generators silently drop keys / whole records (exit 0). Guard with `(xs \| add // 0)`, `(xs \| min_by(.x) // 0)`; guard denominators with `if length == 0 then 0 else ... end`; verify against a filtered-to-empty input slice (§2.4 mechanics). |
| Groups split oddly / wrong group order | Key not normalized before `group_by` (case/whitespace splits one logical group) or mixed-type keys — jq 1.6 does NOT error, it orders by type (null < false < true < number < string < array < object), which is never the intended semantics. Normalize/coerce the key first; groups arrive ascending, so `sort_by(length) \| reverse` when count/total order is required. |
| jq 1.7 vs 1.6 differences | `--indent n` only exists in 1.7; avoid it (default 2-space satisfies the family). `ascii_downcase`, `gsub`, `unique`, `sort_by`, `index` behave identically in 1.6 and 1.7 for this family's usage. |

## 7. Verification checklist

- [ ] Output file exists, is valid JSON, 2-space indentation, and is the ONE
      JSON value the task asked for (array, object, or nested combination).
- [ ] Input shape handled (top-level array, or wrapper object iterated at the
      correct path); input file itself never modified.
- [ ] Every output record passes all selection predicates re-derived from the
      source; every candidate that should be excluded is absent (counts add up).
- [ ] Normalization (trim/lowercase/parse) happens before every comparison,
      dedup, and sort it applies to.
- [ ] Output fields exactly match the task's names; defaults/fallbacks present
      where source values are missing/null/blank.
- [ ] Sort verified: keys in declared order and directions, ties stable and
      legal (input order for full ties when no tie-break is declared) —
      proven with the adjacent-pair invariant (`jq -e '[range(0; length-1)
      as $i | (.[$i].K1 < .[$i+1].K1 or (.[$i].K1 == .[$i+1].K1 and .[$i].K2
      >= .[$i+1].K2))] | all' OUT.json`, direction-flipped as needed) AND
      cross-checked against a second sort idiom.
- [ ] `jq_args.yaml` has exactly `filter` and `args`; `cmd.sh` begins with
      `jq ` (verified via `head -1`), contains the same command with
      redirection, and `bash cmd.sh` reproduces the output
      byte-identically; no Python/Ruby involved in producing the report.
- [ ] Replay robustness: the saved command runs cleanly (exit 0) against
      perturbed inputs — removed optional keys, nulls, extra whitespace,
      case changes — and preserves the task's semantics on each.
- [ ] Single-workflow aggregates: the filtered set is materialized ONCE with
      `(...) as $v` (no double-consumed streams); every `_by`/`add` over a
      possibly-empty subset carries an explicit `//` fallback and guarded
      denominators — verified by running the filter against a
      filtered-to-empty input slice (no vanished keys, no division errors,
      group keys normalized before `group_by`).