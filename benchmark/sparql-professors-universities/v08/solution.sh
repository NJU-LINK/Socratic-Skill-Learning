#!/bin/bash

cat <<'EOF' > /app/solution.sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?prof a uni:Person ;
        uni:hasName ?professorName ;
        uni:role ?role ;
        uni:worksAt ?workplace .

  FILTER(
    REGEX(STR(?role), "^\\s*Professor($|[\\s,.;:()/-])", "i") ||
    REGEX(STR(?role), "^\\s*Assistant\\s+Professor($|[\\s,.;:()/-])", "i") ||
    REGEX(STR(?role), "^\\s*Full\\s+Professor($|[\\s,.;:()/-])", "i")
  )

  ?workplace (uni:partOfFaculty|uni:locatedOnCampus|uni:partOfUniversity)* ?university .
  ?university a uni:University ;
              uni:hasName ?universityName .
}
ORDER BY ?professorName ?universityName
EOF
