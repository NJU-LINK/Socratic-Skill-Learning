# Quick Reference: Common Patterns

## Professor Identification Patterns

### Pattern A: String-valued role (most common)
```sparql
?person uni:role ?role .
FILTER(REGEX(LCASE(?role), "(^|[^a-zA-Z])prof"))
```

**Rationale:** Matches "prof" at start of string or after non-letter (space, period, comma).
XPath/XSD-compatible. Captures "Professor", "Prof.", "Prof", "Assistant Prof.", etc.
Rejects "proofreader", "proctor".

### Pattern B: Resource-based academic rank
```sparql
?person uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?rankLabel .
FILTER(REGEX(LCASE(?rankLabel), "(^|[^a-zA-Z])prof"))
```

### Pattern C: UNION fallback (both patterns)
```sparql
{
  ?person uni:role ?role .
  FILTER(REGEX(LCASE(?role), "(^|[^a-zA-Z])prof"))
}
UNION
{
  ?person uni:hasAcademicRank ?rank .
  ?rank uni:rankLabel ?rankLabel .
  FILTER(REGEX(LCASE(?rankLabel), "(^|[^a-zA-Z])prof"))
}
```

**Fallback filter (if regex unsupported):**
```sparql
FILTER(CONTAINS(LCASE(?role), "professor") || 
       CONTAINS(LCASE(?role), "prof.") || 
       CONTAINS(LCASE(?role), "prof ") ||
       STRSTARTS(LCASE(?role), "prof"))
```

## Affiliation Path Patterns

### Two-hop via department (most common)
```sparql
?person uni:worksAt ?dept .
?dept uni:partOfUniversity ?uni .
```

### Direct affiliation
```sparql
?person uni:affiliatedWith ?uni .
```

### Via appointment resource
```sparql
?person uni:hasAppointment ?appt .
?appt uni:atOrganization ?uni .
```

### Inverse containment
```sparql
?uni uni:employs ?person .
```

### Teaching-course fallback
```sparql
{
  ?person uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?uni .
}
UNION
{
  ?person uni:teaches ?course .
  ?course uni:isTaughtIn ?dept .
  ?dept uni:partOfUniversity ?uni .
}
```

## University Name Patterns

### Most common
```sparql
?uni uni:hasName ?universityName .
```

### Alternatives
```sparql
?uni uni:name ?universityName .
?uni rdfs:label ?universityName .
```

## Discovery Probes

### Find predicates with literal values on Person
```sparql
SELECT DISTINCT ?pred WHERE {
  ?person a uni:Person ; ?pred ?val .
  FILTER(isLiteral(?val))
}
```

### Find predicates with resource values on Person
```sparql
SELECT DISTINCT ?pred ?val WHERE {
  ?person a uni:Person ; ?pred ?val .
  FILTER(isIRI(?val))
}
```

### Find direct Person→University predicates
```sparql
SELECT DISTINCT ?pred WHERE {
  ?person a uni:Person .
  ?person ?pred ?uni .
  ?uni a uni:University .
}
```

### Find two-hop Person→University paths
```sparql
SELECT DISTINCT ?p1 ?p2 WHERE {
  ?person a uni:Person .
  ?person ?p1 ?mid .
  ?mid ?p2 ?uni .
  ?uni a uni:University .
}
```

### Find University name predicates
```sparql
SELECT DISTINCT ?pred WHERE {
  ?uni a uni:University ; ?pred ?name .
  FILTER(isLiteral(?name))
}
```

## Validation Queries

### Check all roles in graph
```sparql
SELECT DISTINCT ?role WHERE {
  ?person uni:role ?role .
}
ORDER BY ?role
```

### Count professors
```sparql
SELECT (COUNT(DISTINCT ?person) AS ?count)
WHERE {
  ?person a uni:Person ;
          uni:role ?role .
  FILTER(REGEX(LCASE(?role), "(^|[^a-zA-Z])prof"))
}
```

### Check for duplicates
```sparql
SELECT ?professorName (COUNT(?universityName) AS ?count)
WHERE {
  ?person uni:hasName ?professorName ;
          <affiliation_path> .
  ?uni uni:hasName ?universityName .
  FILTER(REGEX(LCASE(?role), "(^|[^a-zA-Z])prof"))
}
GROUP BY ?professorName
HAVING (?count > 1)
```
