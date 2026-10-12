#!/bin/bash
set -euo pipefail

cat > /app/solution.sparql <<'EOF'
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor uni:role ?role ;
             uni:hasName ?professorName .

  {
    ?professor uni:worksAt ?department .
  }
  UNION
  {
    FILTER NOT EXISTS { ?professor uni:worksAt ?anyDepartment . }
    ?professor uni:teaches ?course .
    ?course uni:isTaughtIn ?department .
  }

  ?department uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .

  FILTER(REGEX(STR(?role), "(^|[^A-Za-z])Professor([^A-Za-z]|$)"))
}
ORDER BY ?professorName ?universityName
EOF
