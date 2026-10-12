#!/usr/bin/env python3
"""
End-to-end drill of the fingerprint DISPATCH FAIL branch (iteration 3+).

Purpose. Every other package regime has live execution evidence (v01 loop:
fingerprint MATCH -> copy reference -> verify PASS, replayed by fresh solvers
in iterations 1 and 2). The FAIL branch has only been validated by isolated
synthetic mutations, never as a complete solving flow. This script rehearses
that flow end-to-end for six spec-declared deviations, exactly as a solver
would run it under the installed Skill:

  mutate graph -> fingerprint (must FAIL exactly its own conjunct)
               -> dispatch mapping names the template edit (walkthrough text)
               -> adapted query run against the mutated graph
               -> independent Python ORACLE derives expected facts (qualifying
                  set, per-person reachable sets, pair multiset)
               -> verify.py must PASS the multiset comparison

Two regimes, both rehearsed:

  PRE-ENCODED machinery (S1-S4): the deviation is already absorbed by the
  stock template, so the adapted query == template. The drill still verifies
  the dispatch flow (fingerprint FAIL -> template handles it unchanged).

  HAND-EDIT regime (S5-S6): axis-2 manual edits the template cannot pre-encode
  (containment-predicate direction rewrite; person-to-organization predicate
  substitution). The drill additionally asserts the STOCK template FAILS on
  the mutated graph (the edit is necessary) and the edited template PASSES
  (the edit is sufficient), and that the edited text differs from stock.

Independence note: the oracle is a plain BFS over the containment edges
(continuing past University-typed nodes, collecting every University-typed
node at any depth, matching '*' + terminal-anchor semantics) with qualification
by role-token OR rankLabel-token. It is parameterized by the graph's own
worksAt predicate and containment predicate/direction (read from the data like
a solver would), but shares no structure with the SPARQL template (no UNION,
no NOT EXISTS, no property paths).

Scenarios:
  S1 [b] missing worksAt (Felix)        -> guarded course fallback, 8 pairs      (pre-encoded)
  S2 [a] rank-resource variant        -> rankLabel signals, 7 pairs             (pre-encoded)
  S3 [c] deep chain (named Faculty)   -> '*' + terminal anchor, 7 pairs         (pre-encoded)
  S4 [c] direct university affiliation-> zero-hop '*' + anchor, 7 pairs         (pre-encoded)
  S5 [c] inverse containment          -> ^uni:hasDepartment* rewrite, 7 pairs   (hand-edit)
  S6 [b] renamed worksAt -> employedBy-> predicate substitution, 7 pairs        (hand-edit)

Usage: python3 drill_fail_branch.py [--graph PATH] [--outdir DIR]
Exit 0 = every scenario's full flow passed; 1 = any assertion failed.
"""
import argparse
import os
import subprocess
import sys
from collections import Counter

import rdflib
from rdflib import Literal, URIRef

UNI = "http://university.org/ontology#"
RDF_TYPE = rdflib.RDF.type
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINGERPRINT = os.path.join(ROOT, "scripts", "fingerprint_v01.py")
VERIFY = os.path.join(ROOT, "scripts", "verify.py")
TEMPLATE = os.path.join(ROOT, "templates", "query_template.sparql")


def load(path="/app/university_graph.ttl"):
    G = rdflib.Graph()
    G.parse(path, format="turtle")
    return G


def U(s):
    return URIRef(UNI + s)


def oracle(G, works_at=U("worksAt"), containment=("partOfUniversity", False)):
    """Independent enumeration of expected facts, per SKILL.md semantics.

    Returns (qualifying: {personName}, reach: {personName: {universityName}},
    pairs: Counter[(personName, universityName)]).

    Semantics as stated in SKILL.md (not as encoded in the SPARQL template):
      1. qualify by rank token: any uni:role literal OR any
         hasAcademicRank->rankLabel literal containing 'professor',
         case-insensitive.
      2. affiliation: if the person has ANY worksAt (parameterized predicate),
         take those units; otherwise take the isTaughtIn units of every course
         they teach. From each unit, BFS along the containment edges
         (parameterized predicate + direction, read from the data: forward for
         unit->parent, reverse for parent->unit), collecting EVERY
         University-typed node at any depth (zero-hop self-binding included).
      3. decorate with the primary name predicate uni:hasName.
      4. count pairs as a multiset (documented pair-reading: absent worksAt +
         multi-university courses -> one row per reachable university).
    """
    Person, University = U("Person"), U("University")
    role, pou_name = U("role"), U(containment[0])
    pou_rev = containment[1]
    hn, rank, rl = U("hasName"), U("hasAcademicRank"), U("rankLabel")

    def qualifies(p):
        for _, _, o in G.triples((p, role, None)):
            if isinstance(o, Literal) and "professor" in str(o).lower():
                return True
        for _, _, res in G.triples((p, rank, None)):
            for _, _, lbl in G.triples((res, rl, None)):
                if isinstance(lbl, Literal) and "professor" in str(lbl).lower():
                    return True
        return False

    def contained_children(node):
        if pou_rev:                      # parent hasContainment unit: parents
            return [s for s, _, _ in G.triples((None, pou_name, node))]
        return list(G.objects(node, pou_name))

    qual_names, reach, pairs = set(), {}, Counter()
    for p, _, _ in G.triples((None, RDF_TYPE, Person)):
        if not qualifies(p):
            continue
        pname = str(next(G.objects(p, hn)))
        qual_names.add(pname)

        units = [o for o in G.objects(p, works_at)]
        if not units:
            for c in G.objects(p, U("teaches")):
                units.extend(G.objects(c, U("isTaughtIn")))

        terminals = set()
        stack, seen = list(units), set()
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            if (node, RDF_TYPE, University) in G:
                terminals.add(node)
            stack.extend(contained_children(node))
        unames = {str(next(G.objects(u, hn))) for u in terminals}
        reach[pname] = unames
        for uname in unames:
            pairs[(pname, uname)] += 1
    return qual_names, reach, pairs


def conj_of(out):
    return [lab for lab in ("[a]", "[b]", "[c]", "[d]") if f"FAIL | {lab}" in out]


def run_fingerprint(graph_path):
    out = subprocess.run(
        [sys.executable, FINGERPRINT, "--graph", graph_path],
        capture_output=True, text=True)
    return out.returncode, conj_of(out.stdout), out.stdout


def run_verify(query_path, graph_path, expected_pairs):
    exp_path = graph_path + ".expected.txt"
    with open(exp_path, "w") as f:
        for name, univ in sorted(expected_pairs.elements()):
            f.write(f"{name}|{univ}\n")
    out = subprocess.run(
        [sys.executable, VERIFY, "--graph", graph_path,
         "--query", query_path, "--expected-file", exp_path],
        capture_output=True, text=True)
    return out.returncode, out.stdout


def adapted_query(text, replacements, tag, outdir):
    """Apply mechanical edits to the template text and write under outdir."""
    edited = text
    for old, new in replacements:
        assert old in edited, f"edit anchor {old!r} not found in template"
        edited = edited.replace(old, new)
    path = os.path.join(outdir, f"drill_{tag}_adapted.sparql")
    open(path, "w").write(edited)
    return path


def drill(name, arrange, expect_conj, expect_qual, expect_reach, expect_pairs,
          walkthrough, oracle_kwargs=None, hand_edit=None, outdir="/tmp"):
    """hand_edit = (tag, replacements), triggers stock-must-fail assertion."""
    print(f"\n=== DRILL {name} ===")
    for line in walkthrough.splitlines():
        print(f"  | {line}")

    g = arrange(load())
    gpath = os.path.join(outdir, f"drill_{name}.ttl")
    g.serialize(gpath, format="turtle")

    # Layer 0: fingerprint fails exactly its own conjunct
    rc, failed, fp_out = run_fingerprint(gpath)
    ok = (rc == 1 and failed == expect_conj)
    print(f"  [0] fingerprint: exit={rc}, failed={failed} "
          f"(want exit=1 failed={expect_conj}) -> {'OK' if ok else 'WRONG'}")
    if not ok:
        print(fp_out)
        return False

    # Layers 1-3: oracle facts (independent BFS)
    kwal, reach, pairs = oracle(g, **(oracle_kwargs or {}))
    ok1 = kwal == set(expect_qual)
    print(f"  [1] oracle qualifying set: {len(kwal)} persons -> "
          f"{'OK' if ok1 else 'MISMATCH'}")
    if not ok1:
        return False
    ok2 = all(reach.get(p, set()) == set(exp)
              for p, exp in expect_reach.items()) and set(reach) == set(expect_reach)
    print(f"  [2] per-person reachable sets: {len(expect_reach)} persons -> "
          f"{'OK' if ok2 else 'MISMATCH'}"
          + (f"  (diff: { {p: (sorted(reach.get(p, set())), sorted(expect_reach.get(p, set()))) for p in set(reach) | set(expect_reach) if reach.get(p, set()) != set(expect_reach.get(p, set()))} })"
             if not ok2 else ""))
    if not ok2:
        return False
    ok3 = dict(pairs) == dict(expect_pairs)
    print(f"  [3] oracle pair multiset: {len(pairs)} pairs -> "
          f"{'OK' if ok3 else 'MISMATCH'}")
    if not ok3:
        print("      derived:", sorted(pairs.elements()))
        print("      wanted :", sorted(expect_pairs.elements()))
        return False

    # Layer 4: adapted query vs stock
    if hand_edit:
        tag, replacements = hand_edit
        stock = open(TEMPLATE).read()
        adapted = adapted_query(stock, replacements, tag, outdir)
        rc_stock, _ = run_verify(TEMPLATE, gpath, pairs)
        rc_edit, vout = run_verify(adapted, gpath, pairs)
        diff_ok = adapted != TEMPLATE
        print(f"  [4] hand-edit regime: stock template on mutated graph -> "
              f"verify exit={rc_stock} (want != 0: edit is NECESSARY) -> "
              f"{'OK' if rc_stock != 0 else 'WRONG - stock unexpectedly passes'}")
        print(f"  [5] edited template differs from stock -> "
              f"{'OK' if diff_ok else 'WRONG - no edit applied'}")
        print(f"  [6] edited template -> verify exit={rc_edit} "
              f"({'PASS' if rc_edit == 0 else 'FAIL - edit insufficient'})")
        if rc_edit != 0:
            print(vout)
        return rc_stock != 0 and diff_ok and rc_edit == 0

    rc4, vout = run_verify(TEMPLATE, gpath, pairs)
    ok4 = rc4 == 0
    print(f"  [4] stock template (pre-encoded machinery) -> verify exit={rc4} "
          f"({'PASS' if ok4 else 'FAIL'})")
    if not ok4:
        print(vout)
    return ok4


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", default="/app/university_graph.ttl")
    ap.add_argument("--outdir", default="/tmp")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    outdir = args.outdir

    results = []
    EXP = "National Technical University of Athens"
    IST = "Instituto Superior Técnico"
    NKUA = "National and Kapodistrian University of Athens"
    MIT = "Massachusetts Institute of Technology"
    SOR = "Sorbonne University"
    LMU = "Ludwig Maximilian University of Munich"
    ALL7 = ["Alex Morgan", "Thomas Berger", "Felix Wagner",
            "Martin Keller", "John Smith", "Marie Dubois", "Stefan Mueller"]
    REACH7 = {"Alex Morgan": {EXP}, "Thomas Berger": {EXP},
              "Felix Wagner": {IST}, "Martin Keller": {NKUA},
              "John Smith": {MIT}, "Marie Dubois": {SOR}, "Stefan Mueller": {LMU}}
    PAIRS7 = Counter({("Alex Morgan", EXP): 1, ("Thomas Berger", EXP): 1,
                      ("Felix Wagner", IST): 1, ("Martin Keller", NKUA): 1,
                      ("John Smith", MIT): 1, ("Marie Dubois", SOR): 1,
                      ("Stefan Mueller", LMU): 1})

    def s1(g):
        g.remove((U("Felix_Wagner"), U("worksAt"), None))
        return g
    results.append(drill(
        "S1_b_missing_worksAt", s1, ["[b]"], ALL7,
        {**REACH7, "Felix Wagner": {IST, EXP}},
        Counter({("Felix Wagner", IST): 1, ("Felix Wagner", EXP): 1,
                 **{k: v for k, v in PAIRS7.items() if k[0] != "Felix Wagner"}}),
        "DISPATCH: conjunct [b] FAILS -> every qualifying person must have "
        "worksAt.\nEDIT [pre-encoded]: keep/activate the guarded course fallback "
        "(teaches -> isTaughtIn -> unit).\n"
        "  Pair-reading: Felix teaches in IST and NTUA, so the fallback yields "
        "BOTH pairs (8 total).",
        outdir=outdir))

    def s2(g):
        for s, p, o in list(g):
            if p == U("role"):
                g.remove((s, p, o))
        for person in ("Alex_Morgan", "Thomas_Berger", "Felix_Wagner",
                       "Martin_Keller", "John_Smith", "Marie_Dubois",
                       "Stefan_Mueller"):
            g.add((U(person), U("hasAcademicRank"), U("ProfessorRank")))
        g.add((U("ProfessorRank"), U("rankLabel"), Literal("Full Professor")))
        return g
    results.append(drill(
        "S2_a_rank_resource", s2, ["[a]"], ALL7, REACH7, PAIRS7,
        "DISPATCH: conjunct [a] FAILS -> rank does not arrive as uni:role "
        "strings (hasAcademicRank/rankLabel present).\n"
        "EDIT [pre-encoded]: axis-1 rank-signal discovery; the template's "
        "BOUND-guarded two-signal filter covers rank resources as-is.",
        outdir=outdir))

    def s3(g):
        g.remove((U("Biology_MIT"), U("partOfUniversity"), U("MIT")))
        g.add((U("SchoolOfScience"), RDF_TYPE, U("Faculty")))
        g.add((U("SchoolOfScience"), U("hasName"), Literal("School of Science")))
        g.add((U("Biology_MIT"), U("partOfUniversity"), U("SchoolOfScience")))
        g.add((U("SchoolOfScience"), U("partOfUniversity"), U("MIT")))
        return g
    results.append(drill(
        "S3_c_deep_chain", s3, ["[c]"], ALL7, REACH7, PAIRS7,
        "DISPATCH: conjunct [c] FAILS -> a worksAt unit reaches a NON-"
        "University target (named intermediate Faculty).\n"
        "EDIT [pre-encoded]: axis-2: '*' + terminal type anchor (already in "
        "the template); the intermediate never leaks.",
        outdir=outdir))

    def s4(g):
        g.remove((U("Alex_Morgan"), U("worksAt"), U("ComputerScience_NTUA")))
        g.add((U("Alex_Morgan"), U("worksAt"), U("NTUA")))
        return g
    results.append(drill(
        "S4_c_direct_affiliation", s4, ["[c]"], ALL7, REACH7, PAIRS7,
        "DISPATCH: conjunct [c] FAILS -> a worksAt object is itself a "
        "University (direct affiliation).\n"
        "EDIT [pre-encoded]: axis-2: zero-hop '*' + terminal anchor (already "
        "in the template); '*' binds the unit itself and the anchor keeps it.",
        outdir=outdir))

    def s5(g):
        # inverse containment: parent uni:hasDepartment unit, no partOfUniversity
        for s, p, o in list(g):
            if p == U("partOfUniversity"):
                g.remove((s, p, o))
        dept_of = {"ComputerScience_NTUA": "NTUA", "MechEngineering_NTUA": "NTUA",
                   "Mathematics_IST": "IST", "Mathematics_Sorbonne": "Sorbonne",
                   "Physics_ETH": "ETHZurich", "Biology_MIT": "MIT",
                   "Sloan_MIT": "MIT", "Engineering_LMU": "LMU",
                   "Engineering_Berkeley": "Berkeley", "Robotics_UPM": "UPM",
                   "HistoryAndPhilosophy_NKUA": "NKUA"}
        for dept, uni in dept_of.items():
            g.add((U(uni), U("hasDepartment"), U(dept)))
        return g
    results.append(drill(
        "S5_c_inverse_containment", s5, ["[c]"], ALL7, REACH7, PAIRS7,
        "DISPATCH: conjunct [c] FAILS -> worksAt units have NO "
        "partOfUniversity edges (containment runs the other way).\n"
        "EDIT [HAND-EDIT]: read the data to decide direction: "
        "grep -c 'hasDepartment' <GRAPH> shows parent->unit.\n"
        "  REPLACE in BOTH branches (worksAt and course fallback):\n"
        "    ?unit uni:partOfUniversity* ?university .\n"
        "  WITH\n"
        "    ?unit ^uni:hasDepartment* ?university .\n"
        "  (terminal anchor ?university a uni:University unchanged)",
        oracle_kwargs={"containment": ("hasDepartment", True)},
        hand_edit=("S5", [("?unit uni:partOfUniversity* ?university .",
                           "?unit ^uni:hasDepartment* ?university .")]),
        outdir=outdir))

    def s6(g):
        # person-to-organization predicate renamed: worksAt -> employedBy
        for s, p, o in list(g):
            if p == U("worksAt"):
                g.remove((s, p, o))
                g.add((s, U("employedBy"), o))
        return g
    results.append(drill(
        "S6_b_renamed_worksAt", s6, ["[b]"], ALL7, REACH7, PAIRS7,
        "DISPATCH: conjunct [b] FAILS -> qualifying persons have no uni:worksAt "
        "triples. NOTE: the [b] hint 'course fallback' alone is INSUFFICIENT "
        "here - every professor also teaches, so the fallback would fire for "
        "all and fabricate Felix -> NTUA.\n"
        "EDIT [HAND-EDIT]: axis-2 predicate discovery: grep the graph for "
        "person->organization edges (here uni:employedBy), then SUBSTITUTE the "
        "predicate at EVERY occurrence site - the primary worksAt branch, the "
        "course-fallback branch (if it mentions it), and above all the FILTER "
        "NOT EXISTS guard (an unsubstituted guard becomes vacuously true and "
        "the fallback fires for everyone):\n"
        "  uni:worksAt -> uni:employedBy (all occurrences)",
        oracle_kwargs={"works_at": U("employedBy")},
        hand_edit=("S6", [("uni:worksAt", "uni:employedBy")]),
        outdir=outdir))

    print("\n" + "=" * 60)
    if all(results):
        print("FAIL-BRANCH DRILL: ALL 6 SCENARIOS PASSED end-to-end "
              "(S1-S4 pre-encoded machinery; S5-S6 hand-edit regime: stock "
              "fails -> edited template passes)")
        return 0
    print("FAIL-BRANCH DRILL: SOME SCENARIOS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())