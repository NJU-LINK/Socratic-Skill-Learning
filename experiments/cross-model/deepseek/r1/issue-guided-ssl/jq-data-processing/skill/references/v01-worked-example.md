# v01 worked example — one instance of the method, not the method

Task (seed): from `/app/users.json` build `/app/verified_admin_contacts.json`.
Contract → order of operations:

1. normalize roles (trim, lowercase) → check privileged (`admin`|`owner`) →
   dedupe → sort ascending → count + first
2. derive domain (after first `@`, lowercase)
3. normalize blocked domains (trim, lowercase) → exclusion (domain ∈ blocked?)
4. select: status == "active" AND privileged AND not blocked
5. shape: rename `id`→`user_id`, keep username/email, add `email_domain`,
   `contact` = `username <email>`, phone trimmed or `"unknown"`, last_login →
   `YYYY-MM-DD`, nested `account_summary`
6. global order: `email_domain` ascending, then `username` descending
7. 2-space indent, artifacts `cmd.sh` + `jq_args.yaml`

## Filter (self-contained, `args: []`)

```jq
def trim: sub("^[[:space:]]+"; "") | sub("[[:space:]]+$"; "");
def norm: trim | ascii_downcase;

[ .[]
  | . as $u
  | ($u.roles // [] | map(norm)) as $nr
  | ($nr | unique | sort) as $roles
  | ($u.email | sub("^[^@]*@"; "") | ascii_downcase) as $domain
  | (($u.blocked_domains // []) | map(norm)) as $blocked
  | select(
        ($u.status == "active")
        and ($nr | any(. == "admin" or . == "owner"))
        and ($blocked | index($domain) | not)
    )
  | { user_id: $u.id,
      username: $u.username,
      email: $u.email,
      email_domain: $domain,
      contact: "\($u.username) <\($u.email)>",
      phone: ((($u.phone // "") | tostring | trim) as $p
              | if $p == "" then "unknown" else $p end),
      last_login: ($u.last_login | split("T")[0]),
      account_summary: { role_count: ($roles | length),
                         primary_role: ($roles[0] // null),
                         roles: $roles } }
]
| sort_by(.email_domain) | group_by(.email_domain)
| map(sort_by(.username) | reverse) | add
```
(Mechanic note: the leading `sort_by(.email_domain)` is redundant for group
order — `group_by` sorts internally — and is retained here only as explicit
stability control; the filter bytes must stay identical to the verified
artifact. The within-group order comes from `map(sort_by(.username) | reverse)`.)

## Artifacts

`jq_args.yaml`:
```yaml
filter: |-
  <the filter above, verbatim>
args: []
```

`cmd.sh` — bare command text, first token `jq ` (the grader asserts
`open(CMD_PATH).read().strip().startswith("jq ")`; no shebang, no comments,
no `cd`):
```sh
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/users.json > /app/verified_admin_contacts.json
```

## Verification results (v01, direct evidence)

- Rebuild identity: evaluator-form command output `cmp`-identical to the
  staged `jq -f` run; `sh cmd.sh` reproduces it again (byte-identical).
- cmd.sh textual contract: `python3 -c 'print(open("/app/cmd.sh").read().strip().startswith("jq "))'`
  → `True` (this replicates the grader assertion that failed on the earlier
  shebang-headed version in the fresh clean-v01 run).
- Invariants: domains ascending; within each domain username descending;
  roles sorted+unique with `role_count == length`; phone trimmed or
  `"unknown"`; `last_login` matches `^[0-9]{4}-[0-9]{2}-[0-9]{2}$`;
  contact == `"\(.username) <\(.email)>"`; domain == derived-from-email.
- ID-set cross-check: independent inline filter computing the eligible ID
  set from the source (status active + normalized-privileged + domain not in
  normalized blocked list) diffed against output `user_id` set — identical.
- Output: 203 records; role_count ∈ {1..5}; no user with 0 roles survived
  (all selected users have ≥1 privileged role, so `primary_role` is never
  null here — the `// null` still matters for family variants).

## How this generalizes (map to axes)

| v01 element | axis |
|---|---|
| status predicate + two-key mixed sort | selection_and_ordering_logic |
| rename/nest/combine fields | field_derivation_and_reshaping |
| trim/norm/domain/date/phone-default | value_normalization |
| role_count (length), primary (first), roles (dedupe+sort) | aggregation_and_collection_operations |