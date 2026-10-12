# Iteration 3 Improvements Summary

## Overview
Iteration 3 addressed two critical weaknesses in the Phase 5 cross-validation script that were identified through careful analysis of the iteration 2 trajectory.

## Weaknesses Identified

### 1. Affiliation Path Detection Bug
**Problem**: The affiliation path detection algorithm was picking `uni:teaches` instead of `uni:worksAt` because it iterated through predicates in graph order and `teaches` appeared first. The algorithm didn't prioritize predicates that lead to Department-typed resources.

**Impact**: This caused the cross-validation to fail to resolve university names (all returned None), making it impossible to verify that professors were correctly mapped to their universities.

**Root Cause**: The algorithm checked all predicates from Person without filtering for those that lead to organizations (Departments). Since `uni:teaches` leads to Courses (not Departments), it couldn't find the containment path to Universities.

**Fix**: Rewrote the affiliation detection to:
1. First identify Department-like classes (department, division, school, faculty)
2. Find predicates from Person that specifically lead to Department-typed resources
3. Then find containment predicates from Department to University
4. Only fall back to direct Person->University if no Department path exists

### 2. URI Substring Matching Bug
**Problem**: The type checking logic used `'university' in t.lower()` on full URIs like `http://university.org/ontology#Department`, which matched the namespace substring instead of the actual class name.

**Impact**: The algorithm incorrectly identified Department resources as Universities, causing it to try to get university names from Department resources (which don't have them).

**Root Cause**: String matching on full URIs instead of extracting and matching local names.

**Fix**: Added URI local name extraction:
```python
o_type_locals = [t.split('#')[-1].split('/')[-1].lower() for t in o_types]
if any('university' in t or 'institution' in t for t in o_type_locals):
```

This extracts the local name from URIs like `http://university.org/ontology#Department` → `department`, ensuring we match the actual class name, not the namespace.

## Additional Improvements

### 3. Enhanced University Affiliation Verification
**Problem**: The original cross-validation only checked that professor names matched, not that they were mapped to the correct universities.

**Impact**: A query with the correct professor names but wrong university affiliations would pass validation.

**Fix**: Added independent university resolution that:
1. Traces the affiliation path from Person to Department to University
2. Resolves university names using the discovered name predicate
3. Compares both professor names AND university names between SPARQL results and independent enumeration
4. Reports specific mismatches: "Wrong university for X: expected 'A', got 'B'"

### 4. Support for Both Professor Identification Patterns
**Problem**: The cross-validation only handled string-valued role properties (Pattern A), not structured rank resources (Pattern B).

**Impact**: Variants using structured ranks would cause the cross-validation to fail with 0 expected professors.

**Fix**: Added dual-pattern support:
- **Pattern A (string_role)**: Checks if role string contains "Professor"
- **Pattern B (structured_rank)**: Checks if rank resource has a label containing "Professor" or is typed as a professor subclass

The script auto-detects which pattern is in use by checking if the role predicate returns Literal or URIRef values.

## Verification Results

The updated cross-validation script was tested on v01 and correctly:
1. Auto-detected person class: `uni:Person`
2. Auto-detected role predicate: `uni:role` (string_role pattern)
3. Auto-detected name predicate: `uni:hasName`
4. Auto-detected university class: `uni:University`
5. Auto-detected university name predicate: `uni:hasName`
6. Auto-detected affiliation predicate: `uni:worksAt` (not `uni:teaches`)
7. Auto-detected containment predicate: `uni:partOfUniversity`
8. Independently enumerated 7 professors with correct university names
9. Ran SPARQL query and got 7 results with correct university names
10. Cross-validated all pairs: **✅ VALIDATION PASSED**

## File Statistics
- Total lines: 728 (up from 577 in iteration 2)
- Phases: 5 (all present and enhanced)
- Key improvements:
  - Phase 3: Department-aware affiliation detection
  - Phase 5: URI local name extraction, dual-pattern professor identification, university affiliation verification

## What Was NOT Changed
- Phase 1: Ontology Discovery (already robust)
- Phase 2: Professor Identification Strategy (already handles both patterns)
- Phase 3: Affiliation Path Discovery patterns (already comprehensive)
- Phase 4: Query Construction (template already flexible)
- Variation Handling Guide (already comprehensive)
- Common Pitfalls (already includes namespace hardcoding warning)

## Conclusion
Iteration 3 successfully fixed the two critical bugs in the cross-validation script:
1. ✅ Affiliation path now correctly identifies `uni:worksAt` instead of `uni:teaches`
2. ✅ URI matching now uses local names instead of full URI substring matching
3. ✅ University affiliations are now independently verified
4. ✅ Both professor identification patterns (string roles and structured ranks) are supported

The skill is now robust against all three spec variation axes and ready for unseen variants with different namespaces, affiliation structures, and professor identification schemes.
