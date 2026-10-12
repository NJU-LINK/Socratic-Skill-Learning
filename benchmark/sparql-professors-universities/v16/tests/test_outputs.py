import os
from pathlib import Path

from rdflib import Graph


GRAPH_PATH = Path(os.environ.get("GRAPH_PATH", "/app/university_graph.ttl"))
QUERY_PATH = Path(os.environ.get("QUERY_PATH", "/app/solution.sparql"))

EXPECTED_ROWS = {
    ("Claire Durand", "Sorbonne University"),
    ("Daniela Weber", "ETH Zurich"),
    ("Karin Sorensen", "National Technical University of Athens"),
    ("Helena Fischer", "Ludwig Maximilian University of Munich"),
    ("Irene Lindqvist", "National and Kapodistrian University of Athens"),
    ("Marcus Hill", "Massachusetts Institute of Technology"),
    ("Mateo Serrano", "Universidad Politécnica de Madrid"),
    ("Henrik Berg", "National Technical University of Athens"),
    ("Teresa Mendes", "Instituto Superior Técnico"),
}

NEAR_MISS_NAMES = {
    "Owen Brooks",
    "Priya Nair",
    "Jonas Reiter",
    "Hugo Silva",
    "Victor Lee",
}

SYNTHETIC_GRAPH = """
@prefix uni: <http://university.org/ontology#> .

uni:North a uni:University ;
    uni:hasName "North University" .

uni:South a uni:University ;
    uni:hasName "South University" .

uni:CollegeAlpha a uni:College ;
    uni:subOrganizationOf uni:North .

uni:DeptAlpha a uni:Department ;
    uni:subOrganizationOf uni:CollegeAlpha .

uni:CenterBeta a uni:Center ;
    uni:belongsTo uni:South .

uni:DeptBeta a uni:Department ;
    uni:subOrganizationOf uni:CenterBeta .

uni:Aria_Sloan a uni:Person ;
    uni:hasName "Aria Sloan" ;
    uni:role "Adjunct Professor of Law" ;
    uni:worksAt uni:DeptAlpha .

uni:Ben_Ito a uni:Person ;
    uni:hasName "Ben Ito" ;
    uni:role "Emeritus Professor of Chemistry" ;
    uni:worksAt uni:DeptBeta .

uni:Cora_Ng a uni:Person ;
    uni:hasName "Cora Ng" ;
    uni:role "Distinguished Professor" ;
    uni:worksAt uni:DeptAlpha .

uni:Diego_Mora a uni:Person ;
    uni:hasName "Diego Mora" ;
    uni:role "Professor of Ethics" ;
    uni:worksAt uni:South .

uni:Eva_Lopez a uni:Person ;
    uni:hasName "Eva Lopez" ;
    uni:role "Prof. of Linguistics" ;
    uni:worksAt uni:North .

uni:Faye_Stone a uni:Person ;
    uni:hasName "Faye Stone" ;
    uni:role "Teaching Professor Assistant" ;
    uni:worksAt uni:DeptAlpha .

uni:Gabe_Park a uni:Person ;
    uni:hasName "Gabe Park" ;
    uni:role "Professor's Assistant" ;
    uni:worksAt uni:North .

uni:Hana_Reed a uni:Person ;
    uni:hasName "Hana Reed" ;
    uni:role "Assistant to the Professor" ;
    uni:worksAt uni:DeptBeta .

uni:Ian_Voss a uni:Person ;
    uni:hasName "Ian Voss" ;
    uni:role "Professoral Fellow" ;
    uni:worksAt uni:North .

uni:Jules_Ford a uni:Person ;
    uni:hasName "Jules Ford" ;
    uni:role "Research Professor Assistant" ;
    uni:worksAt uni:DeptBeta .
"""

SYNTHETIC_EXPECTED_ROWS = {
    ("Aria Sloan", "North University"),
    ("Ben Ito", "South University"),
    ("Cora Ng", "North University"),
    ("Diego Mora", "South University"),
    ("Eva Lopez", "North University"),
}

DUPLICATE_RISK_GRAPH = """
@prefix uni: <http://university.org/ontology#> .

uni:West a uni:University ;
    uni:hasName "West University" .

uni:SchoolWest a uni:School ;
    uni:partOfUniversity uni:West .

uni:DeptWest a uni:Department ;
    uni:partOfUniversity uni:West ;
    uni:subOrganizationOf uni:SchoolWest .

uni:Kira_Bose a uni:Person ;
    uni:hasName "Kira Bose" ;
    uni:role "Full Professor of Statistics" ;
    uni:worksAt uni:DeptWest .
"""


def run_query():
    assert GRAPH_PATH.exists(), f"Missing graph file: {GRAPH_PATH}"
    assert QUERY_PATH.exists(), f"Missing query file: {QUERY_PATH}"

    query = QUERY_PATH.read_text(encoding="utf-8")
    assert "?professorName" in query
    assert "?universityName" in query

    graph = Graph()
    graph.parse(GRAPH_PATH, format="turtle")
    rows = list(graph.query(query))
    normalized = {(str(row.professorName), str(row.universityName)) for row in rows}
    return rows, normalized


def run_query_on_turtle(turtle_data: str):
    query = QUERY_PATH.read_text(encoding="utf-8")
    graph = Graph()
    graph.parse(data=turtle_data, format="turtle")
    rows = list(graph.query(query))
    normalized = {(str(row.professorName), str(row.universityName)) for row in rows}
    return rows, normalized


def test_query_returns_exact_expected_rows():
    _, normalized = run_query()
    assert normalized == EXPECTED_ROWS


def test_query_has_no_duplicate_rows():
    rows, normalized = run_query()
    assert len(rows) == len(normalized)


def test_query_excludes_near_miss_titles():
    _, normalized = run_query()
    returned_names = {name for name, _ in normalized}
    assert returned_names.isdisjoint(NEAR_MISS_NAMES)


def test_query_handles_broader_professor_titles_and_affiliation_paths():
    _, normalized = run_query_on_turtle(SYNTHETIC_GRAPH)
    assert normalized == SYNTHETIC_EXPECTED_ROWS


def test_query_uses_distinct_for_multi_path_affiliations():
    rows, normalized = run_query_on_turtle(DUPLICATE_RISK_GRAPH)
    assert normalized == {("Kira Bose", "West University")}
    assert len(rows) == 1
