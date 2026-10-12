# SPARQL Professors-Universities Skill - Validation Report

## Overview

This document validates the sparql-professors-universities skill package against
the v01 seed variant and demonstrates its ability to handle variant data models.

## v01 Validation

### Test Setup
- **Input:** `/app/university_graph.ttl` (176 lines, 9 universities, 11 departments)
- **Data Model:** String-based roles + two-hop department-mediated affiliation
- **Expected Output:** 7 professors with their universities

### Results

```
Query executed successfully: YES
Number of results: 7

Results:
  Martin Keller               → National and Kapodistrian University of Athens
  Thomas Berger          → National Technical University of Athens
  John Smith                     → Massachusetts Institute of Technology
  Marie Dubois                   → Sorbonne University
  Alex Morgan                   → National Technical University of Athens
  Felix Wagner                 → Instituto Superior Técnico
  Stefan Mueller                 → Ludwig Maximilian University of Munich

Validation checks:
✓ All expected professors found: True
✓ No lecturers included: True
✓ No students included: True
✓ Correct number of results: True

STATUS: ✓ ALL CHECKS PASSED
```

### Applied Patterns
- **Axis 1:** Pattern 1A (String role with CONTAINS)
- **Axis 2:** Pattern 2A (Two-hop via department)
- **Axis 3:** SELECT DISTINCT

### Query Used
```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:role ?role ;
          uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
  FILTER(CONTAINS(?role, "Professor"))
}
```

---

## Variant Validation

### Test Setup
- **Input:** Synthetic variant graph with resource-based ranks + direct university affiliation
- **Data Model:** Resource-based ranks (uni:hasAcademicRank → uni:rankLabel) + direct affiliation
- **Expected Output:** 2 professors (Alice Johnson, Bob Williams), excluding 1 lecturer

### Diagnostic Analysis

The skill's diagnostic queries successfully identified:
1. **Role representation:** Resource-based ranks via `uni:hasAcademicRank`
2. **Qualifying ranks:** "Professor" and "Assistant Professor" (via `uni:rankLabel`)
3. **Affiliation structure:** Direct person → university links (no intermediate department)

### Results

```
Results: 2 professors found
  Alice Johnson             → Harvard University
  Bob Williams              → Stanford University

✓ Lecturer correctly excluded
✓ Skill successfully handled variant data model
```

### Applied Patterns
- **Axis 1:** Pattern 1D (Resource-based ranks)
- **Axis 2:** Pattern 2B (Direct university affiliation)
- **Axis 3:** SELECT DISTINCT

### Query Used
```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:hasAcademicRank ?rank ;
          uni:worksAt ?university .
  ?rank uni:rankLabel ?rankLabel .
  ?university a uni:University ;
              uni:hasName ?universityName .
  FILTER(?rankLabel = "Professor" || ?rankLabel = "Assistant Professor")
}
```

---

## Skill Package Structure

```
skill/sparql-professors-universities/
├── SKILL.md                          # Main procedure and axis framework
├── references/
│   ├── data-models.md                # Known data layouts (7 models documented)
│   └── sparql-patterns.md            # Reusable SPARQL building blocks
└── VALIDATION.md                     # This file
```

## Key Capabilities Demonstrated

1. **Axis-aware pattern selection:** Skill correctly identified which patterns to apply
   based on data model inspection
2. **Variant handling:** Successfully adapted from v01 (string roles + two-hop) to variant
   (resource ranks + direct affiliation)
3. **Diagnostic workflow:** Used inspection queries to understand unknown data models
4. **Deduplication:** SELECT DISTINCT correctly handled in both cases
5. **Exclusion logic:** Non-qualifying roles (Lecturer, Student) correctly filtered

## Conclusion

The sparql-professors-universities skill package provides a robust, reusable procedure
for generating SPARQL queries across the task family. It successfully handles the v01
seed variant and demonstrates the flexibility to handle variant data models by selecting
appropriate patterns from the catalog rather than rewriting the entire approach.
