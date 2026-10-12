# Reusable SPARQL Building Blocks

This document provides tested SPARQL pattern fragments for the
sparql-professors-universities task family. Each pattern is annotated with
when to use it and how it composes with other patterns.

## 1. Professor Identification Patterns

### 1A. String Role with CONTAINS (v01 default)

**When to use:** Roles are string literals containing "Professor" as a substring.
Both "Professor of X" and "Assistant Professor of X" should qualify.

```sparql
?person a uni:Person ;
        uni:role ?role .
FILTER(CONTAINS(?role, "Professor"))
```

**Notes:**
- Simple and effective for v01-style data
- May over-match if "Visiting Professor" or "Professor Emeritus" should be excluded
- Case-sensitive by default; use `LCASE(?role)` for case-insensitive matching

### 1B. Exact String Role Enumeration

**When to use:** Roles are string literals and only specific values should qualify.

```sparql
?person a uni:Person ;
        uni:role ?role .
FILTER(?role = "Professor" || ?role = "Assistant Professor" || ?role = "Full Professor")
```

**Notes:**
- Precise control over qualifying roles
- Must enumerate all valid role strings
- Does not match "Professor of Computer Science" unless that exact string is listed

### 1C. Substring Match with Exclusions

**When to use:** Roles are strings, "Professor" substring should match, but certain
variants should be excluded.

```sparql
?person a uni:Person ;
        uni:role ?role .
FILTER(CONTAINS(?role, "Professor") &&
       !CONTAINS(?role, "Emeritus") &&
       !CONTAINS(?role, "Visiting"))
```

**Notes:**
- Combines inclusion and exclusion criteria
- Flexible for handling near-miss roles

### 1D. Resource-Based Rank

**When to use:** Ranks are resources with label properties.

```sparql
?person a uni:Person ;
        uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?rankLabel .
FILTER(?rankLabel = "Professor" || ?rankLabel = "Assistant Professor")
```

**Notes:**
- Two-step traversal: person → rank resource → label string
- More structured than string roles
- Requires knowledge of the rank ontology

### 1E. Union of String and Resource Patterns

**When to use:** Graph contains both string roles and resource-based ranks.

```sparql
{
  ?person uni:role ?role .
  FILTER(CONTAINS(?role, "Professor"))
}
UNION
{
  ?person uni:hasAcademicRank ?rank .
  ?rank uni:rankLabel ?rankLabel .
  FILTER(?rankLabel = "Professor" || ?rankLabel = "Assistant Professor")
}
```

**Notes:**
- Captures professors regardless of representation
- SELECT DISTINCT needed to deduplicate if a person matches both patterns

---

## 2. Affiliation Patterns

### 2A. Two-Hop via Department (v01 default)

**When to use:** Person → department → university chain.

```sparql
?person uni:worksAt ?dept .
?dept uni:partOfUniversity ?university .
```

**Notes:**
- Most common pattern in academic ontologies
- Department is an intermediate node

### 2B. Direct University Affiliation

**When to use:** Person links directly to a university.

```sparql
?person uni:worksAt ?university .
?university a uni:University .
```

**Notes:**
- No intermediate department
- Type check ensures target is a university

### 2C. Union of Two-Hop and Direct

**When to use:** Graph may contain both structures.

```sparql
{
  ?person uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?university .
}
UNION
{
  ?person uni:worksAt ?university .
  ?university a uni:University .
}
```

**Notes:**
- Handles heterogeneous data
- SELECT DISTINCT needed

### 2D. Inverse Containment

**When to use:** Department → university link uses `uni:hasDepartment` (inverse direction).

```sparql
?person uni:worksAt ?dept .
?university uni:hasDepartment ?dept .
```

**Notes:**
- Triple direction is reversed compared to 2A
- Check for `uni:hasDepartment` or similar inverse predicates

### 2E. Appointment Resources

**When to use:** Affiliations are reified as appointment resources.

```sparql
?person uni:hasAppointment ?appt .
?appt uni:atOrganization ?university .
```

**Notes:**
- More complex structure allows metadata on the appointment
- May also carry rank or temporal information

### 2F. Teaching Fallback

**When to use:** Some professors lack `uni:worksAt` but teach courses.

```sparql
{
  ?person uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?university .
}
UNION
{
  ?person uni:teaches ?course .
  ?course uni:isTaughtIn ?dept .
  ?dept uni:partOfUniversity ?university .
}
```

**Notes:**
- Primary path via worksAt, fallback via teaching
- Ensures no professors are missed due to missing worksAt

---

## 3. University Name Retrieval

### 3A. Standard hasName

**When to use:** University has a `uni:hasName` property.

```sparql
?university uni:hasName ?universityName .
```

**Notes:**
- Most common pattern
- Returns string literal

### 3B. Label Property

**When to use:** University uses `rdfs:label` instead of `uni:hasName`.

```sparql
?university rdfs:label ?universityName .
```

**Notes:**
- Standard RDF pattern
- May need PREFIX for rdfs namespace

---

## 4. Deduplication Strategies

### 4A. SELECT DISTINCT (Recommended Default)

```sparql
SELECT DISTINCT ?professorName ?universityName
WHERE { ... }
```

**When to use:** Always, as a baseline. Handles:
- Duplicate bindings from UNION patterns
- Multiple matching paths to same university
- Overlapping pattern matches

### 4B. GROUP BY with Aggregation

```sparql
SELECT ?professorName (SAMPLE(?universityName) AS ?uniName)
WHERE { ... }
GROUP BY ?professorName
```

**When to use:** When you need to aggregate or when DISTINCT is insufficient.
Rarely needed for this task family.

---

## 5. Complete Query Templates

### Template A: v01 Default (String Roles + Two-Hop)

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

### Template B: Resource Ranks + Two-Hop

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:hasAcademicRank ?rank ;
          uni:worksAt ?dept .
  ?rank uni:rankLabel ?rankLabel .
  ?dept uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
  FILTER(?rankLabel = "Professor" || ?rankLabel = "Assistant Professor")
}
```

### Template C: Mixed Identification + Heterogeneous Affiliation

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName .
  
  {
    ?person uni:role ?role .
    FILTER(CONTAINS(?role, "Professor"))
  }
  UNION
  {
    ?person uni:hasAcademicRank ?rank .
    ?rank uni:rankLabel ?rankLabel .
    FILTER(?rankLabel = "Professor" || ?rankLabel = "Assistant Professor")
  }
  
  {
    ?person uni:worksAt ?dept .
    ?dept uni:partOfUniversity ?university .
  }
  UNION
  {
    ?person uni:worksAt ?university .
    ?university a uni:University .
  }
  
  ?university uni:hasName ?universityName .
}
```

---

## 6. Diagnostic Queries

Use these to inspect an unknown graph and determine which patterns to apply.

### 6A. Find Role Predicates and Values

```sparql
SELECT DISTINCT ?rolePred ?roleVal (COUNT(?p) AS ?count)
WHERE {
  ?p a uni:Person .
  ?p ?rolePred ?roleVal .
  FILTER(REGEX(STR(?rolePred), "role|rank|position|title", "i"))
}
GROUP BY ?rolePred ?roleVal
ORDER BY DESC(?count)
```

### 6B. Trace Affiliation Paths

```sparql
SELECT ?person ?pred ?obj ?objType
WHERE {
  ?person a uni:Person .
  ?person ?pred ?obj .
  OPTIONAL { ?obj a ?objType }
  FILTER(?pred NOT IN (uni:role, uni:hasName, uni:hasAcademicRank))
}
LIMIT 50
```

### 6C. Check for Department vs University Targets

```sparql
SELECT ?person ?worksAtTarget ?targetType
WHERE {
  ?person uni:worksAt ?worksAtTarget .
  OPTIONAL { ?worksAtTarget a ?targetType }
}
LIMIT 20
```
