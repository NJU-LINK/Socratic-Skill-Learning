#!/bin/bash

cat <<'EOF' > /app/solution.sparql
PREFIX uni: <http://university.org/ontology#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor a uni:Person ;
    uni:hasName ?professorName ;
    uni:role ?role ;
    uni:worksAt ?organization .

  FILTER(CONTAINS(LCASE(STR(?role)), "professor"))
  FILTER(isIRI(?organization))

  # Follow the affiliation chain generically from the workplace node to the
  # university so the query still works when hidden graphs insert or remove
  # intermediate organization layers.
  ?organization (!rdf:type)+ ?university .

  ?university a uni:University ;
    uni:hasName ?universityName .
}
ORDER BY ?professorName ?universityName
EOF
