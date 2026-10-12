# Common SPARQL Patterns for Professor-University Queries

## Role/Rank Filtering Patterns

### String-valued role (v01 pattern)
```sparql
?person uni:role ?role .
FILTER(CONTAINS(LCASE(?role), "professor"))
```

### Resource-valued academic rank
```sparql
?person uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?rankLabel .
FILTER(CONTAINS(LCASE(?rankLabel), "professor"))
```

### Excluding near-misses (if needed)
```sparql
FILTER(CONTAINS(LCASE(?role), "professor"))
FILTER(!CONTAINS(LCASE(?role), "emeritus"))  # example exclusion
```

## Affiliation Chain Patterns

### Two-hop via department (v01)
```sparql
?person uni:worksAt ?dept .
?dept uni:partOfUniversity ?university .
```

### As property path
```sparql
?person uni:worksAt/uni:partOfUniversity ?university .
```

### Direct affiliation
```sparql
?person uni:affiliatedWith ?university .
```

### Alternative paths with UNION
```sparql
{
  ?person uni:worksAt/uni:partOfUniversity ?university .
}
UNION
{
  ?person uni:affiliatedWith ?university .
}
```

### Inverse containment
```sparql
?university uni:hasDepartment ?dept .
?dept uni:hasMember ?person .
```

### Fallback via teaching (when worksAt is absent)
```sparql
{
  ?person uni:worksAt/uni:partOfUniversity ?university .
}
UNION
{
  ?person uni:teaches ?course .
  ?course uni:isTaughtIn ?dept .
  ?dept uni:partOfUniversity ?university .
  FILTER NOT EXISTS { ?person uni:worksAt ?anyDept . }
}
```

## University Name Extraction

### Standard pattern
```sparql
?university uni:hasName ?universityName .
```

### With type anchor
```sparql
?university a uni:University .
?university uni:hasName ?universityName .
```

## Cardinality Enforcement

### Always use DISTINCT for this family
```sparql
SELECT DISTINCT ?professorName ?universityName
WHERE { ... }
```

### If multiple universities per professor need collapsing
```sparql
SELECT ?professorName (GROUP_CONCAT(DISTINCT ?universityName; SEPARATOR=", ") AS ?universities)
WHERE { ... }
GROUP BY ?professorName
```
