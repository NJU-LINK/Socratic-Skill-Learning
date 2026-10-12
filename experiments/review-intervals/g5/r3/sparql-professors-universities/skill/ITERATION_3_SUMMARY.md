# Iteration 3 Summary

## Changes Made

### 1. Enhanced Discovery Section
**Problem:** The skill only mentioned SPARQL probes for schema discovery, but the iteration-2 solver used `grep`/`sed` for text inspection (which was more efficient for the small v01 file).

**Solution:** Added "Discovery: Two Approaches" section that acknowledges both methods:
- **Approach A: Text Inspection** (small files < 500 lines) — Use `grep` to quickly identify predicates and patterns
- **Approach B: SPARQL Probes** (large files or complex structure) — Run SPARQL queries to discover schema programmatically

**Rationale:** Different variants may have different file sizes and complexity. Small files are faster to inspect directly; large files benefit from programmatic discovery.

### 2. Preserved Working Elements
- Concise SKILL.md (~5KB) — effective for solver comprehension
- Decision tree for quick pattern selection
- Placeholder-based query templates (`<AFFILIATION_PATH>`, `<NAME_PREDICATE>`)
- XPath-compatible regex filter `(^|[^a-zA-Z])prof`
- Validation one-liner using rdflib
- Key invariants and common pitfalls

## v01 Solution

**File:** `/app/solution.sparql`

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:role ?role ;
          uni:worksAt ?dept .
  
  ?dept uni:partOfUniversity ?uni .
  ?uni uni:hasName ?universityName .
  
  FILTER(REGEX(LCASE(?role), "(^|[^a-zA-Z])prof"))
}
```

**Results:** 7 professors correctly identified
- Alex Morgan → National Technical University of Athens
- Thomas Berger → National Technical University of Athens
- Felix Wagner → Instituto Superior Técnico
- Martin Keller → National and Kapodistrian University of Athens
- John Smith → Massachusetts Institute of Technology
- Marie Dubois → Sorbonne University
- Stefan Mueller → Ludwig Maximilian University of Munich

**Validation:** ✓ All tests passed
- No lecturers/students in results
- No duplicates
- Both variables bound for all rows
- Correct professor-university pairs

## Discovery Process (Text Inspection Approach)

1. **Role representation:** `grep -n "role\|Person\|Professor"` revealed `uni:role` with string values → Pattern A
2. **Affiliation path:** `grep -n "worksAt\|partOfUniversity"` revealed 2-hop path
3. **University name:** `grep -n "hasName\|University"` revealed `uni:hasName`

## Key Improvements Over Iteration 2

1. **Flexibility:** Solver can choose discovery approach based on file size/complexity
2. **Efficiency:** Text inspection is faster for small files (as demonstrated in iteration 2)
3. **Robustness:** SPARQL probes available for large/complex files where text inspection is impractical
4. **Clarity:** Explicit guidance on when to use each approach

## Family Variation Coverage

### Axis 1: Professor Identification
✓ String-valued roles (Pattern A)
✓ Resource-based ranks (Pattern B)
✓ Both patterns (Pattern C UNION)
✓ Abbreviation handling (regex filter)

### Axis 2: Affiliation Structure
✓ Direct affiliation (1-hop)
✓ Department chain (2-hop)
✓ Appointment resources (2-hop)
✓ Inverse containment
✓ Teaching-course fallback (UNION)

### Axis 3: Graph Noise
✓ DISTINCT for duplicates
✓ Non-professor exclusion (regex filter)
✓ Validation procedure

## Lessons Learned

1. **Multiple discovery approaches** — Different variants benefit from different discovery methods
2. **Efficiency matters** — Text inspection is faster for small files; don't force SPARQL probes when unnecessary
3. **Flexibility over rigidity** — Skills should accommodate multiple valid approaches
4. **Preserve what works** — Iteration 2's concise SKILL.md was effective; don't over-engineer

## Next Steps for Agent

When encountering a new variant:
1. Check file size: `wc -l /app/university_graph.ttl`
2. If small (< 500 lines): Use Approach A (text inspection with `grep`)
3. If large or complex: Use Approach B (SPARQL probes)
4. Identify pattern (A, B, or C) from decision tree
5. Discover affiliation path and name predicate
6. Construct query using template with placeholders
7. Validate using Python one-liner

The skill now provides clear guidance for both discovery approaches, making it robust across the full family of variants.
