#!/bin/bash

set -euo pipefail

cat > /app/solution.sparql <<'EOF'
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName .

  {
    ?person uni:role ?role .
    FILTER(REGEX(LCASE(STR(?role)), "(^|[^a-z])assistant\\s+professor([^a-z]|$)|(^|[^a-z])professor([^a-z]|$)"))
    FILTER(!REGEX(LCASE(STR(?role)), "postdoc|postdoctoral|lecturer"))
  }
  UNION
  {
    ?person uni:hasAcademicRank ?rank .
    OPTIONAL { ?rank uni:rankLabel ?rankLabel }
    FILTER(
      ?rank IN (uni:FullProfessorRank, uni:AssistantProfessorRank)
      || REGEX(LCASE(STR(?rank)), "assistantprofessor|fullprofessor")
      || (
        BOUND(?rankLabel)
        && REGEX(LCASE(STR(?rankLabel)), "(^|[^a-z])assistant\\s+professor([^a-z]|$)|(^|[^a-z])professor([^a-z]|$)")
        && !REGEX(LCASE(STR(?rankLabel)), "postdoc|postdoctoral|lecturer")
      )
    )
  }

  ?person uni:worksAt ?org .
  ?org (
    uni:partOfUniversity
    | uni:belongsToUniversity
    | uni:partOf
    | uni:affiliatedWithUniversity
  )+ ?university .
  ?university a uni:University ;
              uni:hasName ?universityName .
}
ORDER BY ?professorName ?universityName
EOF
