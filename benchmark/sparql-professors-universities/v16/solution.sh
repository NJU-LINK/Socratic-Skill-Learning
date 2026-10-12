#!/bin/bash
set -euo pipefail

app_dir="${APP_DIR:-/app}"

mkdir -p "$app_dir"

cat > "$app_dir/solution.sparql" <<'EOF'
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:role ?role ;
          uni:worksAt ?organization .

  ?organization (uni:partOfUniversity|uni:partOf|uni:subOrganizationOf|uni:belongsTo|uni:affiliatedWith|uni:withinUniversity|uni:organizationPartOf|uni:memberOf|uni:unitOf|uni:departmentOf|uni:facultyOf|uni:schoolOf|uni:divisionOf|^uni:hasDepartment|^uni:hasUnit)* ?university .
  ?university a uni:University ;
              uni:hasName ?universityName .

  BIND(LCASE(STR(?role)) AS ?roleText)

  FILTER(REGEX(?roleText, "(^|[^a-z])(professor|prof\\.)($|[^a-z])"))
  FILTER(!REGEX(?roleText, "professor'?s\\s+assistant"))
  FILTER(!REGEX(?roleText, "(^|[^a-z])assistant[ ]+to[ ]+(the[ ]+)?professor([^a-z]|$)"))
  FILTER(!REGEX(?roleText, "(^|[^a-z])professor'?s[ ]+assistant([^a-z]|$)"))
  FILTER(!REGEX(?roleText, "(^|[^a-z])(teaching[ ]+|research[ ]+)?(professor|prof\\.)[ ]+assistant([^a-z]|$)"))
  FILTER(!REGEX(?roleText, "\\bassistant\\s+to\\s+(the\\s+)?professor\\b"))
  FILTER(!REGEX(?roleText, "\\b(professor|prof\\.)\\s+assistant\\b"))
  FILTER(!REGEX(?roleText, "\\b(professor|prof\\.)\\s+secretary\\b"))
  FILTER(!REGEX(?roleText, "\\b(professor|prof\\.)\\s+coordinator\\b"))
  FILTER(!REGEX(?roleText, "\\b(professor|prof\\.)\\s+administrator\\b"))
  FILTER(!REGEX(?roleText, "\\bprofessoral\\b"))
}
ORDER BY ?professorName ?universityName
EOF
