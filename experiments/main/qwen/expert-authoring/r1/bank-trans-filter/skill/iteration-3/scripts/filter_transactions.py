#!/usr/bin/env python3
"""
Bank transaction entity-resolution filter.
NOTE: This script is a reference copy. The canonical version is embedded
in SKILL.md and must be deployed into /app via heredoc before execution.

Usage:
    python3 filter_transactions.py "Target Company Name" [input_csv] [output_json]
"""
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
