#!/bin/bash
set -euo pipefail

cat <<'EOF' > /app/solution.sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person uni:hasName ?professorName ;
          uni:role ?role ;
          uni:worksAt ?affiliation .

  FILTER(
    REGEX(LCASE(STR(?role)), "(^|[^a-z])(assistant\\s+professor|full\\s+professor|professor)([^a-z]|$)") &&
    !REGEX(LCASE(STR(?role)), "(^|[^a-z])(associate|adjunct|visiting|emeritus|research|clinical|guest)([^a-z]|$)")
  )

  {
    ?affiliation a uni:University ;
                 uni:hasName ?universityName .
  }
  UNION
  {
    ?affiliation (
      uni:partOfUniversity|
      uni:partOf|
      ^uni:hasDepartment|
      ^uni:hasUnit|
      ^uni:hasFaculty|
      ^uni:hasSchool|
      ^uni:containsDepartment|
      ^uni:containsUnit|
      ^uni:containsOrganization|
      ^uni:hasSubOrganization
    )+ ?university .
    ?university a uni:University ;
                uni:hasName ?universityName .
  }
}
ORDER BY ?professorName ?universityName
EOF
