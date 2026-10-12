---
name: sparql-professors-universities
description: >
  Methodology for constructing SPARQL queries that retrieve professor names
  together with their affiliated university names from a Turtle knowledge graph.
  Handles variation in how professor roles are represented (string predicates,
  rank resources, abbreviations), how affiliation paths connect persons to
  universities (direct, via departments, via courses, inverse containment),
  and how noise entities (students, lecturers, staff) must be excluded while
  preserving exactly one row per qualifying professor-university pair.
---

# SPARQL Professors–Universities Query Skill

## Purpose

Given a Turtle (`.ttl`) file containing an ontology and instance data describing
universities, departments, employees, and students, produce a SPARQL query that
returns every qualifying professor's name alongside the name of the university
they work at. The output must have exactly one row per professor–university pair
with the requested projection variables.

## Family Axes (What Varies)

| Axis | v01 Seed | Possible Variants |
|------|----------|-------------------|
| **Professor identification** | `uni:role` string values like `"Professor of X"`, `"Assistant Professor of X"` | `uni:hasAcademicRank` + `uni:rankLabel` resources; abbreviations ("Prof.", "Asst. Prof."); near-miss roles ("Professor's Assistant", "Vice-Professor"); explicit VALUES list of rank URIs |
| **Affiliation structure** | `uni:worksAt` → `uni:Department` → `uni:partOfUniversity` → `uni:University` | Direct `worksAtUniversity` predicate; longer chains through organizational units; inverse containment (`uni:hasMember`); fallback via `uni:teaches` → course → department → university |
| **Noise & cardinality** | Students with `uni:role "Student"`, a Lecturer, no duplicates | Multiple departments per university, professors with multiple affiliations, duplicate role signals requiring DISTINCT |

## Methodology (4 Steps)

> **MANDATORY: Run the exploration script first.**
> Before constructing any query, you **must** execute the exploration script. Its output replaces manual Steps 1–3 below. Do not skip this step, even for small files. The script discovers the actual graph structure, enumerates role values, traces affiliation paths, and provides a RECOMMENDATION section that tells you exactly which predicates and filters to use. Skipping exploration is the most common cause of failure — it leads to hardcoded assumptions that break on variants.

> **Script location:** The skill scripts are mounted at `/skill/scripts/` inside the task container. Use `python3 /skill/scripts/explore_graph.py <ttl_file>` to run the exploration script, and `python3 /skill/scripts/verify_query.py <ttl_file> <sparql_file>` to verify your query. Always use `python3`, not `python`.

### Step 1: Run the Exploration Script

**Action:** Execute `python3 /skill/scripts/explore_graph.py <ttl_file>` and read its output.

The script performs automated discovery:
- **Section 2 (Predicate Inventory):** Lists all predicates with counts and sample values
- **Section 3 (Class Inventory):** Shows all rdf:type classes and instance counts
- **Section 4 (Role/Rank Analysis):** Enumerates all role/rank values on Person instances and classifies each as professor or non-professor
- **Section 5 (Affiliation Path):** Traces paths from Person to University, showing which predicates link persons to departments or directly to universities
- **RECOMMENDATION:** Tells you exactly which role predicate to use, which filter is safe, and which affiliation path to follow

**Why this is mandatory:** Visual inspection of `.ttl` files is error-prone. The script discovers the actual graph structure rather than relying on assumptions. It handles variants with different predicate names, rank resources, or complex affiliation chains.

**Worked example (v01):** Running `python3 /skill/scripts/explore_graph.py /app/university_graph.ttl` produces:
- Role predicate: `uni:role`
- Qualifying values: 6 professor roles (all contain "Professor")
- Non-qualifying: "Lecturer", "Student"
- Recommendation: `FILTER(CONTAINS(?role, "Professor"))` is safe
- Affiliation: `uni:worksAt` → department → `uni:partOfUniversity` → university

### Step 2: Construct the SPARQL Query

**Action:** Using the RECOMMENDATION section from the explore_graph.py output, construct your SPARQL query.

**Template structure:**

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  # 1. Bind the person and their name
  ?professor a uni:Person ;
             uni:hasName ?professorName .
  
  # 2. Apply professor-qualification filter
  #    (use the role predicate and filter recommended by explore_graph.py)
  ?professor uni:role ?role .
  FILTER(CONTAINS(?role, "Professor"))
  
  # 3. Follow affiliation path to university
  #    (use the path shown in Section 5 of the exploration report)
  ?professor uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?university .
  
  # 4. Bind university name
  ?university uni:hasName ?universityName .
}
ORDER BY ?professorName
```

**Key invariants:**
- Always use `SELECT DISTINCT` to prevent duplicate rows.
- Always bind both `?professorName` and `universityName` as the task requires.
- The `a uni:Person` type check helps exclude non-person entities.
- `ORDER BY` is optional but aids verification.
- **Use the exact predicates from the exploration report, not hardcoded assumptions.**

### Step 3: Verify the Query

**Action:** Execute `python3 /skill/scripts/verify_query.py <ttl_file> <sparql_file>` to test your query.

**Checks:**
- Row count matches the number of qualifying professors from the exploration report.
- No non-professors appear (no students, lecturers, staff).
- Each professor appears exactly once.
- University names are correct (cross-reference with the exploration report).

## Common Pitfalls

| Pitfall | Consequence | Prevention |
|---------|-------------|------------|
| Hardcoding `CONTAINS(?role, "Professor")` without checking for near-misses | False positives (e.g., "Professor's Assistant") | Always check the RECOMMENDATION from the exploration script (Step 1) |
| Assuming a fixed 2-hop affiliation path | Misses professors in variants with direct links or longer chains | Use the affiliation path from the exploration script (Step 1) |
| Omitting `DISTINCT` | Duplicate rows when professor has multiple roles or departments | Always include `SELECT DISTINCT` |
| Forgetting to filter out non-professors | Students, lecturers, staff appear in results | Explicit classification of role values |
| Using wrong predicate namespace | Query returns no results | Copy prefix exactly from the `.ttl` file |

## Variant-Specific Adaptations

### When roles use `uni:hasAcademicRank` resources

Replace string filtering with resource matching:
```sparql
?professor uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?rankLabel .
FILTER(CONTAINS(?rankLabel, "Professor"))
```
Or use a VALUES list if rank URIs are known:
```sparql
VALUES ?rank { uni:FullProfessor uni:AssistantProfessor }
```

### When affiliation is direct (no department intermediate)

```sparql
?professor uni:worksAtUniversity ?university .
```

### When fallback via teaching is needed

```sparql
{
  ?professor uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?university .
}
UNION
{
  ?professor uni:teaches ?course .
  ?course uni:isTaughtIn ?dept .
  ?dept uni:partOfUniversity ?university .
}
```

### When multiple departments per university cause duplicates

`SELECT DISTINCT` handles this. If the task requires a specific department, add it to the projection.

## References

- `/skill/scripts/explore_graph.py` — Automated graph exploration that discovers predicates, enumerates roles, and traces affiliation paths. **Must be run before constructing any query.** Execute with `python3 /skill/scripts/explore_graph.py <ttl_file>`.
- `/skill/scripts/verify_query.py` — Reusable Python script for testing any SPARQL query against a Turtle file. Execute with `python3 /skill/scripts/verify_query.py <ttl_file> <sparql_file>`.
