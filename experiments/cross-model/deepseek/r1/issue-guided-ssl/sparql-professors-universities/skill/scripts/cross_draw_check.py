#!/usr/bin/env python3
"""Cross-draw discriminator for Knob A (professor identification).

Reproduces and guards against the iteration-1 evaluator failure:
a query whose Knob A enumerates the EXACT role literals observed in one
draw passes that draw but silently drops qualifying professors whose
title form is unseen in it (evaluated v01 instances are regenerated:
names, title strings, and professor cardinality vary; predicates, types,
and the task's semantic rule are fixed).

Builds two synthetic v01-style draws:
  Draw A: familiar qualifying literals ("Professor of …",
          "Assistant Professor of …") plus near misses (Associate
          Professor, Professor Emeritus), Lecturer, Student.
  Draw B: Draw A plus an UNSEEN qualifying form "Full Professor of
          Robotics" plus a Visiting Professor near miss and a Student.
Demo semantics: qualifying = plain/assistant/full professor titles;
Associate/Emeritus/Visiting/Lecturer/Student are distractors.

Checks (all must hold):
  1. OLD (six-literal VALUES enumeration) passes Draw A  -> local success
     proves nothing across draws.
  2. OLD fails Draw B, dropping exactly the unseen qualifying person
     -> reproduces the evaluator failure mechanism.
  3. NEW (anchor-family regex + explicit emeritus subtraction) passes
     BOTH draws and excludes every near miss.
  4. The pure anchor regex (no subtraction) captures "Professor
     Emeritus" (trailing-status titles pass the prefix anchor) - this is
     printed as evidence that demoted anchor-passing literals require
     the subtraction amendment.
Exit code is 0 only when all four hold.
"""
import sys
import rdflib

NS_PREFIXES = (
    "@prefix uni: <http://university.org/ontology#> .\n"
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
)

DRAW_A = NS_PREFIXES + """
uni:U1 a uni:University ; uni:hasName "Alpha University" .
uni:U2 a uni:University ; uni:hasName "Beta University" .
uni:D1 a uni:Department ; uni:partOfUniversity uni:U1 .
uni:D2 a uni:Department ; uni:partOfUniversity uni:U2 .
uni:D3 a uni:Department ; uni:partOfUniversity uni:U1 .
uni:D4 a uni:Department ; uni:partOfUniversity uni:U2 .
uni:P1 a uni:Person ; uni:hasName "Ada Lovelace" ; uni:role "Professor of Computer Science" ; uni:worksAt uni:D1 .
uni:P2 a uni:Person ; uni:hasName "Grace Hopper" ; uni:role "Assistant Professor of Computer Science" ; uni:worksAt uni:D1 .
uni:P3 a uni:Person ; uni:hasName "Alan Turing" ; uni:role "Professor of Mathematics" ; uni:worksAt uni:D2 .
uni:P4 a uni:Person ; uni:hasName "Emmy Noether" ; uni:role "Professor of Mathematics" ; uni:worksAt uni:D2 .
uni:P5 a uni:Person ; uni:hasName "Katherine Johnson" ; uni:role "Professor of Biology" ; uni:worksAt uni:D3 .
uni:P6 a uni:Person ; uni:hasName "Mary Jackson" ; uni:role "Assistant Professor of Engineering" ; uni:worksAt uni:D4 .
uni:P7 a uni:Person ; uni:hasName "Near Miss Associate" ; uni:role "Associate Professor" ; uni:worksAt uni:D3 .
uni:P8 a uni:Person ; uni:hasName "Near Miss Emeritus" ; uni:role "Professor Emeritus" ; uni:worksAt uni:D4 .
uni:P9 a uni:Person ; uni:hasName "Just A Lecturer" ; uni:role "Lecturer" ; uni:worksAt uni:D4 .
uni:P10 a uni:Person ; uni:hasName "Student Alpha" ; uni:role "Student" .
"""

DRAW_B = DRAW_A + """
uni:P11 a uni:Person ; uni:hasName "Robotics Newcomer" ; uni:role "Full Professor of Robotics" ; uni:worksAt uni:D4 .
uni:P12 a uni:Person ; uni:hasName "Visiting Scholar" ; uni:role "Visiting Professor" ; uni:worksAt uni:D3 .
uni:P13 a uni:Person ; uni:hasName "Student Beta" ; uni:role "Student" .
"""

# OLD mechanism (iteration-1): closed VALUES list of the six observed literals.
OLD_QUERY = """PREFIX uni: <http://university.org/ontology#>
SELECT DISTINCT ?n WHERE {
  ?p a uni:Person ; uni:role ?role ; uni:hasName ?n ; uni:worksAt/uni:partOfUniversity ?u .
  ?u a uni:University .
  VALUES ?role {
    "Professor of Computer Science"
    "Assistant Professor of Computer Science"
    "Professor of Mathematics"
    "Professor of Biology"
    "Assistant Professor of Engineering"
  }
}"""

# NEW mechanism: semantic anchor-family inclusion (case-insensitive prefix
# over accepted rank anchors) + explicit subtraction of demoted
# anchor-passing statuses (here: "professor emeritus" per demo semantics).
NEW_QUERY = """PREFIX uni: <http://university.org/ontology#>
SELECT DISTINCT ?n WHERE {
  ?p a uni:Person ; uni:role ?role ; uni:hasName ?n ; uni:worksAt/uni:partOfUniversity ?u .
  ?u a uni:University .
  FILTER(REGEX(LCASE(?role), "^(assistant\\\\s+|full\\\\s+)?(prof\\\\.|professor)"))
  FILTER(LCASE(?role) NOT IN ("professor emeritus"))
}"""

# Pure anchor (no subtraction): demonstrates the emeritus caveat.
ANCHOR_ONLY_QUERY = NEW_QUERY.replace(
    'FILTER(LCASE(?role) NOT IN ("professor emeritus"))\n', "")


def names_for(graph_text, query_text):
    g = rdflib.Graph()
    g.parse(data=graph_text, format="turtle")
    return sorted(str(r[0]) for r in g.query(query_text))


def main():
    exp_a = {"Ada Lovelace", "Grace Hopper", "Alan Turing", "Emmy Noether",
             "Katherine Johnson", "Mary Jackson"}
    exp_b = exp_a | {"Robotics Newcomer"}

    old_a = set(names_for(DRAW_A, OLD_QUERY))
    old_b = set(names_for(DRAW_B, OLD_QUERY))
    new_a = set(names_for(DRAW_A, NEW_QUERY))
    new_b = set(names_for(DRAW_B, NEW_QUERY))
    anchor_a = set(names_for(DRAW_A, ANCHOR_ONLY_QUERY))
    anchor_b = set(names_for(DRAW_B, ANCHOR_ONLY_QUERY))

    print("== cross-draw discriminator ==")
    print(f"Draw A: qualifying={len(exp_a)}  Draw B: qualifying={len(exp_b)}")
    print(f"OLD (VALUES enumeration):  A={len(old_a)} rows (passes: {old_a == exp_a})"
          f"   B={len(old_b)} rows (passes: {old_b == exp_b})")
    print(f"   -> missing on B: {sorted(exp_b - old_b)}")
    print(f"NEW (anchor + subtraction): A={len(new_a)} rows (passes: {new_a == exp_a})"
          f"   B={len(new_b)} rows (passes: {new_b == exp_b})")
    print(f"   -> near misses excluded: "
          f"{not ({'Near Miss Associate','Near Miss Emeritus','Visiting Scholar','Just A Lecturer','Student Alpha','Student Beta'} & (new_a | new_b))}")
    print(f"PURE anchor (no subtraction): A={len(anchor_a)} B={len(anchor_b)};"
          f" captures emeritus on A: {'Near Miss Emeritus' in anchor_a}"
          f" -> demoted anchor-passing literals need the subtraction amendment")

    ok = True
    checks = [
        ("OLD passes Draw A (local success is draw-specific)", old_a == exp_a),
        ("OLD fails Draw B exactly like the evaluator (drops unseen form)",
         old_b == exp_a and old_b != exp_b),
        ("NEW passes BOTH draws", new_a == exp_a and new_b == exp_b),
        ("NEW excludes all near misses", not (
            {"Near Miss Associate", "Near Miss Emeritus", "Visiting Scholar",
             "Just A Lecturer", "Student Alpha", "Student Beta"} & (new_a | new_b))),
        ("Pure-anchor emeritus capture is visible (caveat demonstrated)",
         "Near Miss Emeritus" in anchor_a),
    ]
    print()
    for label, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    if ok:
        print("\nDISCRIMINATOR OK: old mechanism reproduced-failed, new mechanism"
              " passed both draws; recorded output is the cross-draw evidence.")
        return 0
    print("\nDISCRIMINATOR FAILED", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())