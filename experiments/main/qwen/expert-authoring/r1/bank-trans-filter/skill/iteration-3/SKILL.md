---
name: bank-trans-filter
description: >
  Filter bank transaction CSVs to extract only rows belonging to a target
  company whose identity must be resolved across spelling, punctuation,
  abbreviation, and legal-suffix variations in company names, while excluding
  separately named entities (advisors, partners, subsidiaries) and handling
  noisy account-number identifiers with near-miss distractor detection.
---

# Bank Transaction Entity-Resolution Filter

## Task Family

You receive a CSV of bank transactions at `/app/data/bank_transactions.csv` and
an instruction naming a target company.  The goal is to output every transaction
that belongs to that company to `/app/data/output.json` as a sorted JSON array,
excluding rows that belong to other entities even when their names superficially
overlap the target.

## Procedure

### Step 1 — Identify the target name

Read the task instruction to extract the target company name.
Example: *"Keep only the transactions that belong to North West Capital"*
→ target = `North West Capital`.

### Step 2 — Deploy and run the filter

The script below is **not** pre-installed in `/app`. Write it into the
container first, then run it.  Copy the entire heredoc block verbatim:

```bash
cat > /app/filter_transactions.py << 'PYEOF'
import csv, json, re, sys
from collections import defaultdict

GENERIC_SUFFIXES = {
    "group","holdings","hldgs","inc","llc","corp","ltd","co","company",
    "corporation","limited","incorporated","plc","gmbh","llp","lp",
    "trust","fund","bank","financial","intl","international","tech",
    "technologies","solutions","systems","industries","services",
}
ENTITY_SUFFIXES = {
    "advisors","advisory","partners","consulting","consultancy",
    "management","wealth","research","labs","laboratories",
    "institute","foundation",
}
ABBREVIATIONS = {
    "cap":"capital","hldgs":"holdings","co":"company","corp":"corporation",
    "inc":"incorporated","ltd":"limited","intl":"international",
    "tech":"technologies","assoc":"associates","mfg":"manufacturing",
    "svc":"services","svcs":"services","dept":"department","div":"division",
    "natl":"national","nat":"national","am":"asset management",
    "nw":"north west","ne":"north east","sw":"south west","se":"south east",
    "n":"north","s":"south","e":"east","w":"west",
}
DIRECTIONAL_COMPOUNDS = {
    "northwest":"north west","northeast":"north east",
    "southwest":"south west","southeast":"south east",
    "northcentral":"north central","southcentral":"south central",
}

def normalize(name):
    name = name.strip().lower()
    name = re.sub(r"[.,'\"!?;:()]"," ",name)
    return re.sub(r"\s+"," ",name)

def expand(name):
    for comp,repl in DIRECTIONAL_COMPOUNDS.items():
        name = re.sub(rf"\b{re.escape(comp)}\b",repl,name)
    out = []
    for t in name.split():
        if t in ABBREVIATIONS: out.extend(ABBREVIATIONS[t].split())
        else: out.append(t)
    return " ".join(out)

def strip_suffixes(tokens):
    while tokens and tokens[-1] in GENERIC_SUFFIXES: tokens = tokens[:-1]
    return tokens

def has_entity_suffix(tokens):
    if not tokens: return False
    if tokens[-1] in ENTITY_SUFFIXES: return True
    if len(tokens)>=2 and f"{tokens[-2]} {tokens[-1]}" in ENTITY_SUFFIXES: return True
    return False

def core_tokens(name):
    return strip_suffixes(expand(normalize(name)).split())

def overlap(qt,tt):
    if not tt: return 0.0
    return sum(1 for t in tt if t in qt)/len(tt)

def edit_distance(a,b):
    if len(a)<len(b): a,b=b,a
    if not b: return len(a)
    prev=list(range(len(b)+1))
    for i,ca in enumerate(a):
        curr=[i+1]
        for j,cb in enumerate(b):
            curr.append(min(curr[j]+1,prev[j+1]+1,prev[j]+(0 if ca==cb else 1)))
        prev=curr
    return prev[-1]

def filter_near_miss(accounts,counts,max_d=2):
    al=sorted(accounts); sus=set()
    for i in range(len(al)):
        for j in range(i+1,len(al)):
            a,b=al[i],al[j]
            if a in sus or b in sus: continue
            if edit_distance(a,b)<=max_d:
                ca,cb=counts.get(a,0),counts.get(b,0)
                if ca>cb: sus.add(b)
                elif cb>ca: sus.add(a)
                else: sus.add(max(a,b))
    return accounts-sus

def run(target,csv_path,out_path):
    with open(csv_path,newline="",encoding="utf-8") as f:
        rows=list(csv.DictReader(f))
    tgt=core_tokens(target)
    if not tgt: sys.exit(f"ERROR: no core tokens from '{target}'")

    by_name=defaultdict(list)
    for r in rows: by_name[r["Company Name"]].append(r)

    aliases=set()
    for cn in by_name:
        ct=core_tokens(cn)
        exp_toks=expand(normalize(cn)).split()
        if overlap(ct,tgt)>=1.0 and not has_entity_suffix(exp_toks):
            aliases.add(cn)

    raw_accts=set(); acct_counts=defaultdict(int)
    for a in aliases:
        for r in by_name[a]:
            ac=r["Account Number"]; raw_accts.add(ac); acct_counts[ac]+=1

    est_accts=filter_near_miss(raw_accts,acct_counts)
    removed=raw_accts-est_accts
    if removed: print(f"Near-miss removed: {sorted(removed)}",file=sys.stderr)

    inc_names=set(aliases); changed=True
    while changed:
        changed=False
        for cn,crs in by_name.items():
            if cn in inc_names: continue
            ct=core_tokens(cn)
            exp_toks=expand(normalize(cn)).split()
            if has_entity_suffix(exp_toks): continue
            if any(r["Account Number"] in est_accts for r in crs):
                if overlap(ct,tgt)>=(0.5 if len(tgt)>1 else 1.0):
                    inc_names.add(cn)
                    for r in crs:
                        ac=r["Account Number"]
                        if ac not in est_accts:
                            if not any(edit_distance(ac,e)<=2 for e in est_accts):
                                est_accts.add(ac); changed=True

    result=[]
    for r in rows:
        cn,ac=r["Company Name"],r["Account Number"]
        if cn in inc_names and ac in est_accts: result.append(r)
        elif ac in est_accts and cn not in inc_names:
            ct=core_tokens(cn)
            exp_toks=expand(normalize(cn)).split()
            if has_entity_suffix(exp_toks): continue
            if overlap(ct,tgt)>=0.5: result.append(r)

    result.sort(key=lambda r:r["Date"])
    keys=["Company Name","Account Number","Date","Amount","Transaction Type","Description"]
    out=[{k:r[k] for k in keys} for r in result]
    with open(out_path,"w",encoding="utf-8") as f:
        json.dump(out,f,indent=2,ensure_ascii=False)
    print(f"Aliases({len(aliases)}): {sorted(aliases)}",file=sys.stderr)
    print(f"Accounts({len(est_accts)}): {sorted(est_accts)}",file=sys.stderr)
    print(f"Rows: {len(out)}",file=sys.stderr)

if __name__=="__main__":
    t=sys.argv[1] if len(sys.argv)>1 else "North West Capital"
    c=sys.argv[2] if len(sys.argv)>2 else "/app/data/bank_transactions.csv"
    o=sys.argv[3] if len(sys.argv)>3 else "/app/data/output.json"
    run(t,c,o)
PYEOF
python3 /app/filter_transactions.py "TARGET NAME"
```

Replace `TARGET NAME` with the actual company name from the task instruction.

### Step 3 — Verify the output

```python
import json
with open("/app/data/output.json") as f:
    data = json.load(f)
assert isinstance(data, list)
required = {"Company Name","Account Number","Date","Amount","Transaction Type","Description"}
for row in data:
    assert set(row.keys()) == required
    for k,v in row.items(): assert isinstance(v, str)
dates = [r["Date"] for r in data]
assert dates == sorted(dates)
for row in data:
    for sfx in ["advisors","advisory","partners"]:
        assert sfx not in row["Company Name"].lower()
print(f"OK: {len(data)} rows, dates sorted, no entity-suffix leaks")
```

## How the Algorithm Works

### Core Identity Tokens
Every company name is normalised (lowercase, strip punctuation, expand
abbreviations like `Cap.`→`capital` / `N.W.`→`north west`, split directional
compounds like `Northwest`→`north west`), then trailing **generic suffixes**
(Group, Holdings, Hldgs, Inc, LLC, Corp, Ltd, Co, …) are stripped.
The remaining tokens are the **core identity tokens**.

### Alias Discovery (Phase 1)
A company name is a target alias when its core tokens have **100 % overlap**
with the target core tokens AND the name has no entity-type suffix.

### Near-Miss Account Detection (Phase 2)
After collecting candidate accounts from alias-matched rows, pairwise
Levenshtein edit-distance comparison is performed.  For any pair within
distance ≤ 2, the account with fewer rows is removed as a distractor.
This catches planted data-entry errors where a legitimate-looking name
is paired with a corrupted (near-miss) account number.

### Propagation (Phase 3)
Rows on established accounts whose names have ≥ 50 % core-token overlap
with the target (and no entity suffix) are included.  Newly discovered
accounts are also subject to near-miss filtering before being added.

### Collection (Phase 4)
A row is included only when **both** conditions are met:
1. The company name is an included alias (or propagated name).
2. The account number is an established account (not a near-miss distractor).

### Suffix Taxonomy

**Generic suffixes** (strip before comparison — may vary freely within one entity):
`Group`, `Holdings/Hldgs`, `Inc`, `LLC`, `Corp`, `Ltd`, `Co/Company`,
`Corporation`, `Limited`, `PLC`, `LLP`, `Trust`, `Fund`, `Bank`, `Financial`,
`International/Intl`, `Technologies/Tech`, `Solutions`, `Systems`, `Industries`,
`Services`

**Entity suffixes** (signal a separate entity — always exclude):
`Advisors`, `Advisory`, `Partners`, `Consulting`, `Consultancy`, `Management`,
`Wealth`, `Research`, `Labs`, `Laboratories`, `Institute`, `Foundation`

## Edge Cases

- **Empty result**: If no names match, output `[]`.
- **Single-token target**: Require exact token match; do not propagate on partial overlap.
- **Account-only evidence**: Never include a row based on account match alone — name evidence is always required.
- **Near-miss account with valid name**: The account-level distractor signal overrides the name-level match.
- **Preserve values exactly**: Amount strings like `"-$197887.00"` keep their original formatting.
- **Multiple legitimate accounts**: Accounts differing by > 2 characters are both legitimate.
