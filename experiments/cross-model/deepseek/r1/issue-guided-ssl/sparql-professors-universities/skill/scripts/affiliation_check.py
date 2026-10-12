#!/usr/bin/env python3
"""Executable axis-2 playbook: affiliation-structure variants.

The spec declares affiliation_structure_to_university variation (direct
links, longer chains, inverse containment, appointment resources,
teaching-course fallback). v01 exercises only one shape
(worksAt -> dept -> partOfUniversity), so this script gives the other
shapes executable evidence: for each synthetic shape it holds the
correct per-shape query template (the reusable Knob B knowledge), runs
it, and asserts the exact professor-university pair set with all
non-professor noise excluded.

Shapes:
  A direct      : person -[worksAt]-> university
  B chain2      : person -[worksAt]-> dept -[partOfUniversity]-> university
  C chain3      : person -[worksAt]-> faculty -[partOfUniversity]-> dept
                  -[partOfUniversity]-> university
  D inverse     : university -[hasDepartment]-> dept; person -[worksAt]-> dept
  E appointment : appt a uni:Appointment; role ON the appointment;
                  -[appointee]-> person, -[atUniversity]-> university
  F course-only : person -[teaches]-> course -[isTaughtIn]-> dept
                  -[partOfUniversity]-> university, no worksAt at all
  F2 crosslink  : professor with worksAt in U1 who ALSO teaches a course
                  taught in U2 ('Felix Wagner' hazard): the fallback
                  must PREFER worksAt, otherwise an unguarded UNION
                  double-binds the professor -> wrong extra row
  G hetero      : HETEROGENEOUS chain (spec: 'longer or heterogeneous
                  organization chains'): P1's dept links to the university
                  in ONE hop via partOfUniversity; P2's dept links in TWO
                  hops via partOfUniversity -> School -> subOrganizationOf
                  -> university. Homogeneous 'partOfUniversity+' repeats
                  ONE predicate and silently drops P2; alternation-in-
                  repetition (partOfUniversity|subOrganizationOf)+ returns
                  both. Hop predicates must be read from
                  trace_affiliations.py signatures, not hardcoded.

Negative assertions: the v01 two-hop template does NOT solve shapes
A/C/D/E/F; Knob A on the Person node fails for E; an UNGUARDED course
fallback double-binds on F2. I.e. trace_affiliations.py must precede
template choice. Requires rdflib; exit 0 only when every assertion holds.
"""
import sys
import rdflib

NS = "http://university.org/ontology#"
P = f"PREFIX uni: <{NS}>\n"
ANCHOR = ('FILTER(REGEX(LCASE(?role), "^(assistant\\\\s+|full\\\\s+)?'
          '(prof\\\\.|professor)"))')

SHAPES = {
    "A_direct": f"""{P}
uni:U1 a uni:University ; uni:hasName "Alpha University" .
uni:U2 a uni:University ; uni:hasName "Beta University" .
uni:P1 a uni:Person ; uni:hasName "Direct Prof One" ; uni:role "Professor of Physics" ; uni:worksAt uni:U1 .
uni:P2 a uni:Person ; uni:hasName "Direct Prof Two" ; uni:role "Assistant Professor of Math" ; uni:worksAt uni:U2 .
uni:L1 a uni:Person ; uni:hasName "Noisy Lecturer" ; uni:role "Lecturer" ; uni:worksAt uni:U1 .
uni:S1 a uni:Person ; uni:hasName "Noisy Student" ; uni:role "Student" .
""",
    "B_chain2": f"""{P}
uni:U1 a uni:University ; uni:hasName "Alpha University" .
uni:D1 a uni:Department ; uni:partOfUniversity uni:U1 .
uni:P1 a uni:Person ; uni:hasName "Chain Prof One" ; uni:role "Professor of CS" ; uni:worksAt uni:D1 .
uni:P2 a uni:Person ; uni:hasName "Chain Prof Two" ; uni:role "Full Professor of Bio" ; uni:worksAt uni:D1 .
uni:L1 a uni:Person ; uni:hasName "Noisy Lecturer" ; uni:role "Lecturer" ; uni:worksAt uni:D1 .
""",
    "C_chain3": f"""{P}
uni:U1 a uni:University ; uni:hasName "Alpha University" .
uni:D1 a uni:Department ; uni:partOfUniversity uni:U1 .
uni:F1 a uni:Faculty ; uni:partOfUniversity uni:D1 .
uni:P1 a uni:Person ; uni:hasName "Deep Prof One" ; uni:role "Professor of Chem" ; uni:worksAt uni:F1 .
uni:P2 a uni:Person ; uni:hasName "Deep Prof Two" ; uni:role "Assistant Professor of Chem" ; uni:worksAt uni:F1 .
uni:L1 a uni:Person ; uni:hasName "Noisy Lecturer" ; uni:role "Lecturer" ; uni:worksAt uni:F1 .
""",
    "D_inverse": f"""{P}
uni:U1 a uni:University ; uni:hasName "Alpha University" ; uni:hasDepartment uni:D1 .
uni:D1 a uni:Department .
uni:P1 a uni:Person ; uni:hasName "Inverse Prof One" ; uni:role "Professor of Mech" ; uni:worksAt uni:D1 .
uni:P2 a uni:Person ; uni:hasName "Inverse Prof Two" ; uni:role "Assistant Professor of Mech" ; uni:worksAt uni:D1 .
uni:L1 a uni:Person ; uni:hasName "Noisy Lecturer" ; uni:role "Lecturer" ; uni:worksAt uni:D1 .
""",
    "E_appointment": f"""{P}
uni:U1 a uni:University ; uni:hasName "Alpha University" .
uni:A1 a uni:Appointment ; uni:appointee uni:P1 ; uni:role "Professor of Law" ; uni:atUniversity uni:U1 .
uni:A2 a uni:Appointment ; uni:appointee uni:P2 ; uni:role "Full Professor of Law" ; uni:atUniversity uni:U1 .
uni:P1 a uni:Person ; uni:hasName "Appointed Prof One" .
uni:P2 a uni:Person ; uni:hasName "Appointed Prof Two" .
uni:L1 a uni:Person ; uni:hasName "Noisy Student" ; uni:role "Student" .
""",
    "F_course_only": f"""{P}
uni:U1 a uni:University ; uni:hasName "Alpha University" .
uni:D1 a uni:Department ; uni:partOfUniversity uni:U1 .
uni:C1 a uni:Course ; uni:isTaughtIn uni:D1 .
uni:P1 a uni:Person ; uni:hasName "TeachesOnly Prof" ; uni:role "Professor of Art" ; uni:teaches uni:C1 .
uni:P2 a uni:Person ; uni:hasName "BothPaths Prof" ; uni:role "Professor of Music" ; uni:teaches uni:C1 ; uni:worksAt uni:D1 .
uni:L1 a uni:Person ; uni:hasName "Noisy Lecturer" ; uni:role "Lecturer" ; uni:worksAt uni:D1 .
""",
    "F2_crosslink": f"""{P}
uni:U1 a uni:University ; uni:hasName "Alpha University" .
uni:U2 a uni:University ; uni:hasName "Beta University" .
uni:D1 a uni:Department ; uni:partOfUniversity uni:U1 .
uni:D2 a uni:Department ; uni:partOfUniversity uni:U2 .
uni:C1 a uni:Course ; uni:isTaughtIn uni:D1 .
uni:C2 a uni:Course ; uni:isTaughtIn uni:D2 .
uni:P1 a uni:Person ; uni:hasName "TeachesOnly Prof" ; uni:role "Professor of Art" ; uni:teaches uni:C1 .
uni:P2 a uni:Person ; uni:hasName "Cross Prof" ; uni:role "Professor of Music" ; uni:teaches uni:C1 ; uni:teaches uni:C2 ; uni:worksAt uni:D1 .
uni:L1 a uni:Person ; uni:hasName "Noisy Lecturer" ; uni:role "Lecturer" ; uni:worksAt uni:D1 .
""",
    "G_hetero": f"""{P}
uni:U1 a uni:University ; uni:hasName "Alpha University" .
uni:D1 a uni:Department ; uni:partOfUniversity uni:U1 .
uni:D2 a uni:Department ; uni:partOfUniversity uni:S1 .
uni:S1 a uni:School ; uni:subOrganizationOf uni:U1 .
uni:P1 a uni:Person ; uni:hasName "Hetero OneHop Prof" ; uni:role "Professor of X" ; uni:worksAt uni:D1 .
uni:P2 a uni:Person ; uni:hasName "Hetero TwoHop Prof" ; uni:role "Full Professor of Y" ; uni:worksAt uni:D2 .
uni:L1 a uni:Person ; uni:hasName "Noisy Lecturer" ; uni:role "Lecturer" ; uni:worksAt uni:D2 .
""",
}

TEMPLATES = {
    "A_direct":
        f"""{P}SELECT DISTINCT ?n ?un WHERE {{
  ?p a uni:Person ; uni:role ?role ; uni:hasName ?n ; uni:worksAt ?u .
  ?u a uni:University ; uni:hasName ?un .
  {ANCHOR} }}""",
    "B_chain2":
        f"""{P}SELECT DISTINCT ?n ?un WHERE {{
  ?p a uni:Person ; uni:role ?role ; uni:hasName ?n ;
     uni:worksAt/uni:partOfUniversity ?u .
  ?u a uni:University ; uni:hasName ?un .
  {ANCHOR} }}""",
    "C_chain3":
        f"""{P}SELECT DISTINCT ?n ?un WHERE {{
  ?p a uni:Person ; uni:role ?role ; uni:hasName ?n ;
     uni:worksAt/uni:partOfUniversity+ ?u .
  ?u a uni:University ; uni:hasName ?un .
  {ANCHOR} }}""",
    "D_inverse":
        f"""{P}SELECT DISTINCT ?n ?un WHERE {{
  ?p a uni:Person ; uni:role ?role ; uni:hasName ?n ;
     uni:worksAt/^uni:hasDepartment ?u .
  ?u a uni:University ; uni:hasName ?un .
  {ANCHOR} }}""",
    "E_appointment":
        f"""{P}SELECT DISTINCT ?n ?un WHERE {{
  ?app a uni:Appointment ; uni:appointee ?p ; uni:role ?role ;
       uni:atUniversity ?u .
  ?p a uni:Person ; uni:hasName ?n .
  ?u a uni:University ; uni:hasName ?un .
  {ANCHOR} }}""",
    "F_course_only":
        f"""{P}SELECT DISTINCT ?n ?un WHERE {{
  ?p a uni:Person ; uni:role ?role ; uni:hasName ?n ;
     uni:teaches/uni:isTaughtIn/uni:partOfUniversity ?u .
  ?u a uni:University ; uni:hasName ?un .
  {ANCHOR} }}""",
    "F2_crosslink":
        # worksAt path PREFERRED; course path only for persons with NO
        # worksAt (guarded fallback - the Felix Wagner hazard).
        f"""{P}SELECT DISTINCT ?n ?un WHERE {{
  ?p a uni:Person ; uni:role ?role ; uni:hasName ?n .
  {{
    ?p uni:worksAt/uni:partOfUniversity ?u .
  }} UNION {{
    ?p uni:teaches/uni:isTaughtIn/uni:partOfUniversity ?u .
    FILTER NOT EXISTS {{ ?p uni:worksAt ?_any . }}
  }}
  ?u a uni:University ; uni:hasName ?un .
  {ANCHOR} }}""",
    "G_hetero_alternation":
        # alternation-in-repetition: '+' repeats ONE hop expression, so
        # heterogeneous chains put the predicate set inside the repetition.
        f"""{P}SELECT DISTINCT ?n ?un WHERE {{
  ?p a uni:Person ; uni:role ?role ; uni:hasName ?n ;
     uni:worksAt/(uni:partOfUniversity|uni:subOrganizationOf)+ ?u .
  ?u a uni:University ; uni:hasName ?un .
  {ANCHOR} }}""",
}

# The v01-shaped template, used for the negative assertions.
V01_TEMPLATE = TEMPLATES["B_chain2"]

EXPECTED = {
    "A_direct": {("Direct Prof One", "Alpha University"),
                 ("Direct Prof Two", "Beta University")},
    "B_chain2": {("Chain Prof One", "Alpha University"),
                 ("Chain Prof Two", "Alpha University")},
    "C_chain3": {("Deep Prof One", "Alpha University"),
                 ("Deep Prof Two", "Alpha University")},
    "D_inverse": {("Inverse Prof One", "Alpha University"),
                  ("Inverse Prof Two", "Alpha University")},
    "E_appointment": {("Appointed Prof One", "Alpha University"),
                      ("Appointed Prof Two", "Alpha University")},
    "F_course_only": {("TeachesOnly Prof", "Alpha University"),
                      ("BothPaths Prof", "Alpha University")},
    "F2_crosslink": {("TeachesOnly Prof", "Alpha University"),
                     ("Cross Prof", "Alpha University")},
    "G_hetero": {("Hetero OneHop Prof", "Alpha University"),
                  ("Hetero TwoHop Prof", "Alpha University")},
}


def run(graph_text, query_text):
    g = rdflib.Graph()
    g.parse(data=graph_text, format="turtle")
    return {(str(a), str(b)) for a, b in g.query(query_text)}


def main():
    print("== axis-2 affiliation-shape playbook ==")
    ok = True
    for name in ["A_direct", "B_chain2", "C_chain3", "D_inverse",
                 "E_appointment", "F_course_only", "F2_crosslink",
                 "G_hetero"]:
        tpl_name = "G_hetero_alternation" if name == "G_hetero" else name
        got = run(SHAPES[name], TEMPLATES[tpl_name])
        exp = EXPECTED[name]
        passed = got == exp
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name:14s} "
              f"template rows={len(got)} expected={len(exp)}"
              + ("" if passed else f"  got={sorted(got)}"))
        if name not in ("B_chain2", "F2_crosslink", "G_hetero"):
            wrong = run(SHAPES[name], V01_TEMPLATE)
            wpass = wrong != exp
            ok = ok and wpass
            print(f"        v01 template on {name}: rows={len(wrong)}"
                  f" (wrong answer, as expected: {wpass})")
    # negative: Knob A on Person node fails for appointment shape
    person_role_q = TEMPLATES["E_appointment"].replace(
        "?app a uni:Appointment ; uni:appointee ?p ; uni:role ?role ;",
        "?p a uni:Person ; uni:role ?role ;")
    got_e = run(SHAPES["E_appointment"], person_role_q)
    epass = got_e == set()
    ok = ok and epass
    print(f"  [{'PASS' if epass else 'FAIL'}] role-on-Person template on "
          f"E_appointment yields {len(got_e)} rows (Knob A must move to the "
          f"appointment node)")
    # G_hetero: homogeneous '+' silently drops the two-hop professor
    homg = run(SHAPES["G_hetero"], TEMPLATES["B_chain2"].replace(
        "uni:worksAt/uni:partOfUniversity ?u .",
        "uni:worksAt/uni:partOfUniversity+ ?u ."))
    hpass = homg == {("Hetero OneHop Prof", "Alpha University")}
    ok = ok and hpass
    print(f"  [{'PASS' if hpass else 'FAIL'}] homogeneous partOfUniversity+ "
          f"on G_hetero returns {sorted(homg)} (silent drop of the two-hop "
          f"professor reproduced: 1 of 2)")
    gpass = run(SHAPES["G_hetero"], TEMPLATES["G_hetero_alternation"]) == \
        EXPECTED["G_hetero"]
    ok = ok and gpass
    print(f"  [{'PASS' if gpass else 'FAIL'}] alternation-in-repetition "
          f"(partOfUniversity|subOrganizationOf)+ on G_hetero returns both "
          f"professors, lecturer excluded")
    # negative: UNGUARDED course fallback double-binds the cross-linking
    # professor (the Felix-Wagner-style wrong second row)
    unguarded = run(SHAPES["F2_crosslink"], TEMPLATES["F_course_only"])
    upass = ("Cross Prof", "Beta University") in unguarded and \
        unguarded != EXPECTED["F2_crosslink"]
    ok = ok and upass
    print(f"  [{'PASS' if upass else 'FAIL'}] unguarded course fallback on "
          f"F2_crosslink produces {sorted(unguarded)} (double-binds Cross "
          f"Prof to Beta University) -> fallback must prefer worksAt "
          f"(FILTER NOT EXISTS / OPTIONAL)")
    print("\n" + ("PLAYBOOK OK: every axis-2 shape solved by its template; "
                  "mismatched templates demonstrably fail" if ok else
                  "PLAYBOOK FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())