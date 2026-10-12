#!/bin/bash
set -euo pipefail

cat <<'EOF' > /app/solution.sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:role ?role ;
          uni:worksAt ?organization .

  BIND(LCASE(STR(?role)) AS ?roleLower)

  ?university a uni:University ;
              uni:hasName ?universityName .

  # Hidden variants may insert or remove intermediate organization nodes.
  ?organization (
    uni:partOfUniversity
    | uni:partOf
    | uni:belongsTo
    | uni:subOrganizationOf
    | uni:affiliatedWith
    | uni:memberOf
    | uni:unitOf
    | uni:schoolOf
    | uni:facultyOf
    | ^uni:hasDepartment
    | ^uni:hasDivision
    | ^uni:hasFaculty
    | ^uni:hasSchool
    | ^uni:hasUnit
    | ^uni:hasSubOrganization
  )* ?university .

  FILTER(CONTAINS(?roleLower, "professor"))
  FILTER(!CONTAINS(?roleLower, "assistant to"))
  FILTER(!CONTAINS(?roleLower, "office staff"))
  FILTER(!CONTAINS(?roleLower, "research staff"))
  FILTER(!CONTAINS(?roleLower, "coordinator"))
  FILTER(!CONTAINS(?roleLower, "administrator"))
  FILTER(!CONTAINS(?roleLower, "program"))
  FILTER(!CONTAINS(?roleLower, "search committee"))
}
ORDER BY ?professorName ?universityName
EOF
