from pathlib import Path

import rdflib


SOLUTION_PATH = Path("/app/solution.sparql")
GRAPH_PATH = Path("/app/university_graph.ttl")


def load_query() -> str:
    assert SOLUTION_PATH.exists(), "/app/solution.sparql was not created"
    query = SOLUTION_PATH.read_text(encoding="utf-8").strip()
    assert query, "/app/solution.sparql is empty"
    return query


def run_query(graph_text: str | None = None):
    query = load_query()
    graph = rdflib.Graph()
    if graph_text is None:
        assert GRAPH_PATH.exists(), "/app/university_graph.ttl is missing"
        graph.parse(GRAPH_PATH, format="ttl")
    else:
        graph.parse(data=graph_text, format="ttl")

    results = graph.query(query)
    return [var.toPython().lstrip("?") for var in results.vars], {
        (str(row[0]), str(row[1])) for row in results
    }


def test_query_returns_exact_expected_rows_for_variant_graph():
    vars_, rows = run_query()

    assert vars_ == ["professorName", "universityName"]
    assert rows == {
        ("Ana Costa", "Helios Polytechnic"),
        ("Camila Ortiz", "Meridian University"),
        ("Elena Marku", "Aurora Technical University"),
        ("Iris Novak", "Danube Research University"),
        ("Jonas Weber", "Cascadia State University"),
        ("Leila Haddad", "Helios Polytechnic"),
        ("Leo Martinez", "Redwood Institute of Science"),
        ("Maya Chen", "Cascadia State University"),
        ("Nikhil Rao", "Aurora Technical University"),
        ("Owen Hart", "Meridian University"),
        ("Pavel Sidorov", "Baltic Institute of Technology"),
        ("Priya Desai", "Redwood Institute of Science"),
        ("Renee Brooks", "Northbridge University"),
        ("Sofia Lind", "Baltic Institute of Technology"),
        ("Tomasz Zielinski", "Danube Research University"),
        ("Victor Stein", "Northbridge University"),
    }


def test_query_handles_multiple_affiliation_paths_without_duplicates():
    vars_, rows = run_query(
        """
        @prefix uni: <http://university.org/ontology#> .

        uni:U1 a uni:University ;
            uni:hasName "Example University" .

        uni:D1 a uni:Department ;
            uni:partOfUniversity uni:U1 .

        uni:I1 a uni:Institute ;
            uni:belongsToUniversity uni:U1 .

        uni:C1 a uni:ResearchCenter ;
            uni:hostedByUniversity uni:U1 .

        uni:Alice a uni:Person ;
            uni:hasName "Alice" ;
            uni:role "Assistant Professor of Data Science" ;
            uni:worksAt uni:D1, uni:I1 ;
            uni:memberOfResearchCenter uni:C1 .
        """
    )

    assert vars_ == ["professorName", "universityName"]
    assert rows == {("Alice", "Example University")}


def test_query_handles_direct_and_multi_hop_affiliations():
    _, rows = run_query(
        """
        @prefix uni: <http://university.org/ontology#> .

        uni:U1 a uni:University ;
            uni:hasName "Direct University" .

        uni:U2 a uni:University ;
            uni:hasName "Layered University" .

        uni:Dept2 a uni:Department ;
            uni:partOfUniversity uni:U2 .

        uni:Inst2 a uni:Institute ;
            uni:partOf uni:Dept2 .

        uni:Lab2 a uni:Laboratory ;
            uni:partOf uni:Inst2 .

        uni:Inez a uni:Person ;
            uni:hasName "Inez" ;
            uni:role "Full Professor of Economics" ;
            uni:worksAt uni:U1 .

        uni:Jules a uni:Person ;
            uni:hasName "Jules" ;
            uni:role "Assistant Professor of Robotics" ;
            uni:worksAt uni:Lab2 .

        uni:Kira a uni:Person ;
            uni:hasName "Kira" ;
            uni:role "Research Scientist" ;
            uni:worksAt uni:U1 .
        """
    )

    assert rows == {
        ("Inez", "Direct University"),
        ("Jules", "Layered University"),
    }


def test_query_matches_professor_titles_but_excludes_professors_assistant():
    _, rows = run_query(
        """
        @prefix uni: <http://university.org/ontology#> .

        uni:U1 a uni:University ;
            uni:hasName "North Example University" .

        uni:U2 a uni:University ;
            uni:hasName "South Example University" .

        uni:D1 a uni:Department ;
            uni:partOfUniversity uni:U1 .

        uni:D2 a uni:Department ;
            uni:partOfUniversity uni:U2 .

        uni:C2 a uni:ResearchCenter ;
            uni:hostedByUniversity uni:U2 .

        uni:Dana a uni:Person ;
            uni:hasName "Dana" ;
            uni:role "Professor, Department of Physics" ;
            uni:worksAt uni:D1 .

        uni:Evan a uni:Person ;
            uni:hasName "Evan" ;
            uni:role "Associate Professor of Biology" ;
            uni:worksAt uni:D2 .

        uni:Faye a uni:Person ;
            uni:hasName "Faye" ;
            uni:role "Visiting Professor in Residence" ;
            uni:memberOfResearchCenter uni:C2 .

        uni:Gary a uni:Person ;
            uni:hasName "Gary" ;
            uni:role "Professor's Assistant for Lab Operations" ;
            uni:worksAt uni:D1 .

        uni:Helen a uni:Person ;
            uni:hasName "Helen" ;
            uni:role "Lecturer" ;
            uni:worksAt uni:D2 .
        """
    )

    assert rows == {
        ("Dana", "North Example University"),
        ("Evan", "South Example University"),
        ("Faye", "South Example University"),
    }
