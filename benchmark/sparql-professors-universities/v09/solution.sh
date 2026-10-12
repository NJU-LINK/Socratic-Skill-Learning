#!/bin/bash
set -euo pipefail

cat > /app/solution.sparql <<'EOF'
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor uni:role ?role ;
             uni:hasName ?professorName ;
             ?affiliationPredicate ?unit .

  VALUES ?affiliationPredicate { uni:worksAt uni:memberOf }

  FILTER(
    CONTAINS(LCASE(STR(?role)), "professor")
  )

  ?unit uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
}
ORDER BY ?professorName ?universityName
EOF
