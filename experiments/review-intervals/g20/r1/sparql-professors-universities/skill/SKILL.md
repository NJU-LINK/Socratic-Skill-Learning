---
name: sparql-professors-universities
description: >
  Construct SPARQL queries that retrieve professors and their affiliated universities
  from a Turtle knowledge graph. Uses property-grounded schema discovery to handle
  variants with different type URIs, role representations, and affiliation structures.
---

# SPARQL Professors-Universities Query Construction

## Task

Given a Turtle (`.ttl`) knowledge graph, write a SPARQL query that:
- Retrieves all professor names (`?professorName`)
- For each professor, retrieves the university name they work at (`?universityName`)
- Returns exactly one row per professor-university pair
- Saves the query to `/app/solution.sparql`

## Procedure

### Step 1: Run Schema Discovery (MANDATORY FIRST STEP)

**Always run the discovery script first.** Do not read the TTL file directly.

```bash
python3 /skill/discover_schema.py /app/university_graph.ttl
```

The script outputs:
- All predicates and their usage counts
- Role/rank predicates (discovered by property name patterns: role, rank, position, title, jobtitle)
- Person-like resources (discovered by carrying role predicates)
- University-like resources (discovered by reachability from persons + having names)
- All paths from person-like to university-like resources (1-3 hops)

**Read the output carefully.** Scroll to the **QUICK SUMMARY** section at the bottom. It explicitly lists:
1. **Namespace prefix** (e.g., `uni:`, `ex:`, `org:`) — with the exact PREFIX line to use
2. **Role predicate** — with the exact SPARQL pattern
3. **Name predicate** — for both persons and universities
4. **Most common affiliation path** — the exact triple pattern to use

Use these directly in your query template. The summary extracts the key information from the verbose output above it.

### Step 2: Identify Professors

From the discovery output, look at the role/rank values. Professors have role strings containing "Professor" (case-insensitive).

**Common patterns:**
- "Professor of X"
- "Assistant Professor of X"
- "Associate Professor of X"

**Non-professors:**
- "Lecturer"
- "Student"
- "Staff"
- "Researcher" (may or may not qualify — check task instructions)

**Build the filter:**
```sparql
FILTER(CONTAINS(LCASE(?role), "professor"))
```

**Important:** Use `LCASE()` for case-insensitive matching. Variants may use "PROFESSOR", "professor", or mixed case.

### Step 3: Trace Affiliation Path

From the discovery output, identify the path from persons to universities.

**Common patterns:**

**Two-hop via department (most common):**
```
?person -> worksAt -> ?department -> partOfUniversity -> ?university
```

**Direct affiliation:**
```
?person -> affiliatedWith -> ?university
```

**Via course teaching (fallback):**
```
?person -> teaches -> ?course -> isTaughtIn -> ?department -> partOfUniversity -> ?university
```

**Use the predicates discovered by the script.** Do not assume predicate names.

### Step 4: Construct the Query

**Template:**
```sparql
PREFIX <ns>: <namespace-uri>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person <name-predicate> ?professorName ;
          <role-predicate> ?role ;
          <worksAt-predicate> ?org .
  ?org <partOfUniversity-predicate> ?university .
  ?university <name-predicate> ?universityName .
  FILTER(CONTAINS(LCASE(?role), "professor"))
}
ORDER BY ?professorName
```

**Critical requirements:**
1. **`SELECT DISTINCT`** — prevents duplicate rows
2. **No type assertions** — do NOT use `?person a <type>`. The role predicate + FILTER IS the person constraint. Type assertions fail when variants use different type URIs.
3. **Correct variable names** — must match task requirements (`?professorName`, `?universityName`)
4. **Proper PREFIX** — use the namespace discovered in Step 1
5. **Correct predicates** — use the predicates discovered by the script

### Step 5: Validate

**Always test the query:**

```python
from rdflib import Graph

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")

with open("/app/solution.sparql") as f:
    query = f.read()

results = g.query(query)
print(f"Results: {len(results)}")
for row in results:
    print(f"  {row.professorName} -> {row.universityName}")
```

**Sanity checks:**
- Count matches expected professors
- No non-professors (students, lecturers, staff) appear
- Each professor appears exactly once
- University names are correct (not department names or URIs)

## Key Principles

### Property-Grounded Discovery

**Never assume type names.** Discover what plays each role by following property structure:
- Person-like = resources carrying role predicates
- University-like = resources reachable from persons + having names

This handles variants with `ex:AcademicStaff`, `foaf:Person`, `org:Organization`, etc.

### Role Predicate as Constraint

The role predicate + FILTER replaces type assertions. This makes queries robust to type URI changes.

### Case-Insensitive Matching

Always use `LCASE()` in role filters to handle case variations.

## Common Pitfalls

1. **Skipping discover_schema.py** — always run it first; don't read TTL directly
2. **Type assertions** — do NOT use `?person a <type>`; the role predicate IS the constraint
3. **Case-sensitive filter** — use `LCASE()` for robustness
4. **Missing DISTINCT** — causes duplicates with multiple paths
5. **Hardcoded predicates** — always discover from the graph
6. **Assuming fixed path length** — affiliation chains vary (1-hop, 2-hop, 3-hop)

## Helper Script

**discover_schema.py** implements property-grounded discovery:
- Finds person-like resources by role predicates (not type names)
- Finds university-like resources by reachability + names
- Traces all paths from persons to universities (1-3 hops)

**Usage:** `python3 /skill/discover_schema.py /path/to/graph.ttl`

This is your **first tool** for every variant.
