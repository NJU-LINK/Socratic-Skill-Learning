#!/bin/bash

set -euo pipefail

cat <<'EOF' > /app/solution.sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:role ?role ;
          uni:worksAt ?affiliation .

  BIND(LCASE(STR(?role)) AS ?roleText)

  FILTER(
    REGEX(?roleText, "prof") &&
    !REGEX(?roleText, "(^|[^a-z])(associate|adjunct|visiting|emeritus|research|guest|clinical|courtesy|honorary|acting|temporary|interim|affiliate|lecturer|student|staff|secretary|postdoc|postdoctoral|fellow)([^a-z]|$)") &&
    (
      REGEX(?roleText, "(^|[^a-z])assistant([^a-z]|$)") ||
      REGEX(?roleText, "(^|[^a-z])full([^a-z]|$)") ||
      !REGEX(?roleText, "(^|[^a-z])(assistant|associate|adjunct|visiting|emeritus|research|guest|clinical|courtesy|honorary|acting|temporary|interim|affiliate)([^a-z]|$)")
    )
  )

  {
    SELECT DISTINCT ?affiliation ?universityName
    WHERE {
      {
        ?affiliation a uni:University ;
                    uni:hasName ?universityName .
      }
      UNION
      {
        ?affiliation ?p1 ?university1 .
        ?university1 a uni:University ;
                     uni:hasName ?universityName .
      }
      UNION
      {
        ?affiliation ?p1 ?node1 .
        ?node1 ?p2 ?university2 .
        FILTER(isIRI(?node1) || isBlank(?node1))
        ?university2 a uni:University ;
                     uni:hasName ?universityName .
      }
      UNION
      {
        ?affiliation ?p1 ?node1 .
        ?node1 ?p2 ?node2 .
        ?node2 ?p3 ?university3 .
        FILTER(isIRI(?node1) || isBlank(?node1))
        FILTER(isIRI(?node2) || isBlank(?node2))
        ?university3 a uni:University ;
                     uni:hasName ?universityName .
      }
      UNION
      {
        ?affiliation ?p1 ?node1 .
        ?node1 ?p2 ?node2 .
        ?node2 ?p3 ?node3 .
        ?node3 ?p4 ?university4 .
        FILTER(isIRI(?node1) || isBlank(?node1))
        FILTER(isIRI(?node2) || isBlank(?node2))
        FILTER(isIRI(?node3) || isBlank(?node3))
        ?university4 a uni:University ;
                     uni:hasName ?universityName .
      }
    }
  }
}
ORDER BY ?professorName ?universityName
EOF
