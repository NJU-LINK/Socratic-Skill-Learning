#!/bin/bash
set -euo pipefail

cat <<'EOF' > /app/solution.sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person uni:hasName ?professorName ;
          uni:role ?role ;
          uni:worksAt ?organization .

  ?organization (uni:partOfUniversity|uni:partOf|uni:subOrganizationOf|^uni:hasDepartment|^uni:hasUnit)* ?university .
  ?university a uni:University ;
              uni:hasName ?universityName .

  FILTER(REGEX(LCASE(STR(?role)), "(^|[^a-z])professor([^a-z]|$)"))
}
ORDER BY ?professorName ?universityName
EOF
