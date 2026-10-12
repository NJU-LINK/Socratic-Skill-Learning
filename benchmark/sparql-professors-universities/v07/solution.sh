#!/bin/bash
set -euo pipefail

cat > /app/solution.sparql <<'EOF'
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:role ?role .

  FILTER(
    REGEX(
      LCASE(STR(?role)),
      "(^|[^a-z])((assistant|associate|full|adjunct|visiting|distinguished|emeritus)\\s+)*professor($|[^a-z'])"
    )
  )

  ?person (uni:worksAt|uni:memberOfResearchCenter) ?org .
  ?org (uni:partOfUniversity|uni:belongsToUniversity|uni:hostedByUniversity|uni:partOf|uni:subOrganizationOf|uni:affiliatedWith)* ?university .
  ?university a uni:University ;
              uni:hasName ?universityName .
}
ORDER BY ?professorName ?universityName
EOF
