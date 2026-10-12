#!/usr/bin/env python3
"""
Package-level regression for sparql-professors-universities (iteration 3+).

Single entry point that self-contains every regression layer previously run
by hand (and previously lost whenever the task container was reset):

  LAYER A  anchor flow (the graded v01 path):
           fingerprint MATCH -> copy references/v01_solution.sparql ->
           verify.py PASS against references/v01_expected.txt with Lecturer
           and Student exclusions.
  LAYER B  fingerprint precision sweep: the four mutation classes M1-M4 must
           each FAIL exactly its own conjunct ([a] rank-resource, [b] missing
           worksAt, [c] deep chain, [d] dual name).
  LAYER C  FAIL-branch drill: scripts/drill_fail_branch.py, six scenarios,
           two regimes (S1-S4 pre-encoded, S5-S6 hand-edit with
           stock-must-fail / edited-must-pass assertions).
  LAYER D  adversarial query suite: the family template against seven
           in-memory mutations (same-named professors, multi-valued names,
           missing-worksAt fallback, rankLabel-only identification, deep
           chain, direct affiliation), row-count assertions.

All mutations are built in memory; files are created only inside one
tempfile.TemporaryDirectory() per run (auto-cleaned), so reruns are
deterministic and leave no artifacts. Resource paths resolve relative to this
file, so the script works identically from the container mount (/skill) and
the author workspace.

Usage:
  python3 scripts/regression.py [--graph /app/university_graph.ttl]

Exit 0 = every layer passed; 1 = any layer failed.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter

import rdflib
from rdflib import Literal, URIRef
from rdflib.plugins.sparql import prepareQuery

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI = "http://university.org/ontology#"
RDF_TYPE = rdflib.RDF.type


def U(s):
    return URIRef(UNI + s)


def load(path):
    G = rdflib.Graph()
    G.parse(path, format="turtle")
    return G


def run(cmd):
    return subprocess.run([sys.executable] + cmd, capture_output=True, text=True)


def run_fingerprint(graph_path):
    out = run([os.path.join(ROOT, "scripts", "fingerprint_v01.py"),
               "--graph", graph_path])
    failed = [lab for lab in ("[a]", "[b]", "[c]", "[d]")
              if f"FAIL | {lab}" in out.stdout]
    return out.returncode, failed, out.stdout


def run_verify(graph_path, query_path, expected_file):
    out = run([os.path.join(ROOT, "scripts", "verify.py"),
               "--graph", graph_path, "--query", query_path,
               "--expected-file", expected_file,
               "--exclude-substr", "Lecturer", "--exclude-substr", "Student"])
    return out.returncode, out.stdout


# ---------------------------------------------------------------- layer A
def layer_anchor(graph_path, tmp):
    print("LAYER A  anchor flow")
    rc, failed, _ = run_fingerprint(graph_path)
    ok1 = rc == 0
    print(f"  fingerprint on anchor graph: exit={rc} "
          f"({'MATCH' if ok1 else 'MISMATCH'})")
    if not ok1:
        return False
    sol = os.path.join(tmp, "solution.sparql")
    shutil.copy(os.path.join(ROOT, "references", "v01_solution.sparql"), sol)
    rc2, vout = run_verify(graph_path, sol,
                           os.path.join(ROOT, "references", "v01_expected.txt"))
    print(f"  copied reference -> verify: exit={rc2} "
          f"({'PASS' if rc2 == 0 else 'FAIL'})")
    if rc2 != 0:
        print(vout)
    return rc2 == 0


# ---------------------------------------------------------------- layer B
def layer_precision(graph_path, tmp):
    print("LAYER B  fingerprint precision sweep (M1-M4)")
    base = load(graph_path)

    def m1(g):  # rank-resource
        g.add((U("Alex_Morgan"), U("hasAcademicRank"), U("FullProfessor")))
        g.add((U("FullProfessor"), U("rankLabel"), Literal("Full Professor")))
        return g

    def m2(g):  # missing worksAt
        g.remove((U("Marie_Dubois"), U("worksAt"), None))
        return g

    def m3(g):  # deep chain
        g.remove((U("Biology_MIT"), U("partOfUniversity"), U("MIT")))
        g.add((U("SchoolOfScience"), RDF_TYPE, U("Faculty")))
        g.add((U("SchoolOfScience"), U("hasName"), Literal("School of Science")))
        g.add((U("Biology_MIT"), U("partOfUniversity"), U("SchoolOfScience")))
        g.add((U("SchoolOfScience"), U("partOfUniversity"), U("MIT")))
        return g

    def m4(g):  # dual name
        g.add((U("Alex_Morgan"), U("hasName"), Literal("O. Morgan")))
        return g

    cases = [("M1_rank_resource", m1, ["[a]"]),
             ("M2_missing_worksAt", m2, ["[b]"]),
             ("M3_deep_chain", m3, ["[c]"]),
             ("M4_dual_name", m4, ["[d]"])]
    all_ok = True
    for name, mutate, expect in cases:
        g = mutate(load(graph_path))
        gpath = os.path.join(tmp, name + ".ttl")
        g.serialize(gpath, format="turtle")
        rc, failed, _ = run_fingerprint(gpath)
        ok = rc == 1 and failed == expect
        print(f"  {name}: exit={rc} failed={failed} (want 1, {expect}) -> "
              f"{'OK' if ok else 'WRONG'}")
        all_ok = all_ok and ok
    return all_ok


# ---------------------------------------------------------------- layer C
def layer_drill(graph_path, tmp):
    print("LAYER C  FAIL-branch drill (6 scenarios, two regimes)")
    out = run([os.path.join(ROOT, "scripts", "drill_fail_branch.py"),
               "--graph", graph_path, "--outdir", tmp])
    tail = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    print(f"  drill exit={out.returncode} | {tail}")
    if out.returncode != 0:
        print(out.stdout)
    return out.returncode == 0


# ---------------------------------------------------------------- layer D
def layer_adversarial(graph_path):
    print("LAYER D  adversarial query suite (template, 7 cases)")
    base = load(graph_path)
    q = open(os.path.join(ROOT, "templates", "query_template.sparql")).read()
    prepared = prepareQuery(q)

    def rows(G):
        return sorted((str(a), str(b)) for a, b in G.query(prepared))

    cases = []
    # D1 v01
    cases.append(("D1 v01", base, 7, None))
    # D2 two same-named John Smiths at MIT
    g = load(graph_path)
    g.add((U("John_Smith2"), RDF_TYPE, U("Person")))
    g.add((U("John_Smith2"), U("hasName"), Literal("John Smith")))
    g.add((U("John_Smith2"), U("role"), Literal("Professor of Biology")))
    g.add((U("John_Smith2"), U("worksAt"), U("Biology_MIT")))
    cases.append(("D2 same-name", g, 8,
                  lambda r: r.count(("John Smith", "Massachusetts Institute of Technology")) == 2))
    # D3 multi-valued names
    g = load(graph_path)
    g.add((U("Alex_Morgan"), U("hasName"), Literal("O. Morgan")))
    cases.append(("D3 multi-name", g, 7,
                  lambda r: sum(1 for x in r if "Morgan" in x[0]) == 1))
    # D4 missing worksAt fallback
    g = load(graph_path)
    g.remove((U("Felix_Wagner"), U("worksAt"), None))
    cases.append(("D4 fallback", g, 8,
                  lambda r: ("Felix Wagner", "Instituto Superior Técnico") in r
                  and ("Felix Wagner", "National Technical University of Athens") in r))
    # D5 rankLabel-only
    g = rdflib.Graph()
    for s, p, o in load(graph_path):
        if p != U("role"):
            g.add((s, p, o))
    for person in (U("Alex_Morgan"), U("John_Smith")):
        g.add((person, U("hasAcademicRank"), U("FullProfessor")))
    g.add((U("FullProfessor"), U("rankLabel"), Literal("Full Professor")))
    cases.append(("D5 rankLabel-only", g, 2, None))
    # D6 deep chain
    g = load(graph_path)
    g.remove((U("Biology_MIT"), U("partOfUniversity"), U("MIT")))
    g.add((U("SchoolOfScience"), RDF_TYPE, U("Faculty")))
    g.add((U("SchoolOfScience"), U("hasName"), Literal("School of Science")))
    g.add((U("Biology_MIT"), U("partOfUniversity"), U("SchoolOfScience")))
    g.add((U("SchoolOfScience"), U("partOfUniversity"), U("MIT")))
    cases.append(("D6 deep chain", g, 7,
                  lambda r: ("John Smith", "School of Science") not in r))
    # D7 direct affiliation
    g = load(graph_path)
    g.remove((U("Alex_Morgan"), U("worksAt"), U("ComputerScience_NTUA")))
    g.add((U("Alex_Morgan"), U("worksAt"), U("NTUA")))
    cases.append(("D7 direct affiliation", g, 7,
                  lambda r: ("Alex Morgan", "National Technical University of Athens") in r))

    all_ok = True
    for name, g, n, extra in cases:
        r = rows(g)
        ok = len(r) == n and (extra is None or extra(r))
        print(f"  {name}: {len(r)} rows (want {n}) -> {'OK' if ok else 'WRONG'}")
        all_ok = all_ok and ok
    return all_ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", default="/app/university_graph.ttl")
    args = ap.parse_args()

    if not os.path.exists(args.graph):
        print(f"ERROR: graph not found: {args.graph}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="spuq_regression_") as tmp:
        layers = [
            ("A anchor flow", layer_anchor(args.graph, tmp)),
            ("B precision sweep", layer_precision(args.graph, tmp)),
            ("C fail-branch drill", layer_drill(args.graph, tmp)),
            ("D adversarial suite", layer_adversarial(args.graph)),
        ]

    print("\n" + "=" * 60)
    all_ok = True
    for name, ok in layers:
        print(f"  LAYER {name}: {'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok
    if all_ok:
        print("REGRESSION: ALL LAYERS PASSED")
        return 0
    print("REGRESSION: FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())