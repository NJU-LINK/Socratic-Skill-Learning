#!/bin/bash
set -euo pipefail

cat <<'EOF' > /app/solution.sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor a uni:Person ;
             uni:hasName ?professorName ;
             uni:role ?role ;
             uni:worksAt ?organization .

  FILTER(REGEX(LCASE(STR(?role)), "(^|[^a-z])((assistant|associate|full|visiting|adjunct)[\\s-]*)?prof(essor|\\.)?([^a-z]|$)"))

  {
    ?organization a uni:University .
    BIND(?organization AS ?university)
  }
  UNION
  {
    ?organization (
      (uni:partOfDepartment|uni:partOfFaculty|uni:partOfSchool|uni:partOfInstitute|uni:partOfLab|uni:partOfCenter|uni:partOfDivision|uni:partOfCollege|uni:partOfOrganization)*
      / uni:partOfUniversity
    ) ?university .
  }

  ?university a uni:University ;
              uni:hasName ?universityName .
}
ORDER BY ?professorName ?universityName
EOF
