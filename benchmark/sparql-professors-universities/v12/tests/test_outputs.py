from pathlib import Path

from rdflib import Graph, Namespace


GRAPH_PATH = Path("/app/university_graph.ttl")
QUERY_PATH = Path("/app/solution.sparql")
UNI = Namespace("http://university.org/ontology#")


def _load_graph():
    graph = Graph()
    graph.parse(GRAPH_PATH, format="turtle")
    return graph


def _run_query(graph):
    query_text = QUERY_PATH.read_text()
    return graph.query(query_text)


def _graph_from_ttl(ttl_text):
    graph = Graph()
    graph.parse(data=ttl_text, format="turtle")
    return graph


def test_solution_file_exists():
    assert QUERY_PATH.exists(), "/app/solution.sparql was not created"


def test_query_returns_exact_variables_and_expected_rows():
    graph = _load_graph()
    results = _run_query(graph)

    assert [str(var) for var in results.vars] == ["professorName", "universityName"]

    actual_pairs = {(str(row.professorName), str(row.universityName)) for row in results}
    expected_pairs = {
        ("Nathan Cole", "University of California, Berkeley"),
        ("Martin Keller", "National and Kapodistrian University of Athens"),
        ("Thomas Berger", "National Technical University of Athens"),
        ("John Smith", "Massachusetts Institute of Technology"),
        ("Marie Dubois", "Sorbonne University"),
        ("Alex Morgan", "National Technical University of Athens"),
        ("Felix Wagner", "Instituto Superior Tecnico"),
        ("Stefan Mueller", "Ludwig Maximilian University of Munich"),
    }
    assert actual_pairs == expected_pairs


def test_query_deduplicates_joint_appointments():
    graph = _load_graph()
    results = list(_run_query(graph))
    actual_pairs = [(str(row.professorName), str(row.universityName)) for row in results]

    assert len(actual_pairs) == len(set(actual_pairs)), "query returned duplicate professor-university rows"

    assert actual_pairs.count(
        ("Alex Morgan", "National Technical University of Athens")
    ) == 1
    assert actual_pairs.count(
        ("Thomas Berger", "National Technical University of Athens")
    ) == 1
    assert actual_pairs.count(
        ("Felix Wagner", "Instituto Superior Tecnico")
    ) == 1


def test_query_rejects_professor_like_non_targets():
    graph = _graph_from_ttl(
        """
        @prefix uni: <http://university.org/ontology#> .

        uni:North a uni:University ;
            uni:hasName "North University" .

        uni:CS a uni:Department ;
            uni:partOfUniversity uni:North .

        uni:Full a uni:Person ;
            uni:hasName "Full Target" ;
            uni:role "Full Professor of Logic" ;
            uni:worksAt uni:CS .

        uni:Plain a uni:Person ;
            uni:hasName "Plain Target" ;
            uni:role "Professor of Databases" ;
            uni:worksAt uni:CS .

        uni:Assistant a uni:Person ;
            uni:hasName "Assistant Target" ;
            uni:role "Assistant Professor, AI Systems" ;
            uni:worksAt uni:CS .

        uni:Associate a uni:Person ;
            uni:hasName "Associate Distractor" ;
            uni:role "Associate Professor of History" ;
            uni:worksAt uni:CS .

        uni:Adjunct a uni:Person ;
            uni:hasName "Adjunct Distractor" ;
            uni:role "Adjunct Professor of Music" ;
            uni:worksAt uni:CS .

        uni:Visiting a uni:Person ;
            uni:hasName "Visiting Distractor" ;
            uni:role "Visiting Professor of Chemistry" ;
            uni:worksAt uni:CS .

        uni:Emeritus a uni:Person ;
            uni:hasName "Emeritus Distractor" ;
            uni:role "Professor Emeritus of Physics" ;
            uni:worksAt uni:CS .
        """
    )

    actual_pairs = {(str(row.professorName), str(row.universityName)) for row in _run_query(graph)}
    assert actual_pairs == {
        ("Assistant Target", "North University"),
        ("Full Target", "North University"),
        ("Plain Target", "North University"),
    }


def test_query_handles_non_seed_affiliation_paths():
    graph = _graph_from_ttl(
        """
        @prefix uni: <http://university.org/ontology#> .

        uni:Central a uni:University ;
            uni:hasName "Central University" .

        uni:West a uni:University ;
            uni:hasName "West University" .

        uni:SchoolOfScience a uni:School ;
            uni:partOf uni:Central .

        uni:DataDept a uni:Department ;
            uni:partOf uni:SchoolOfScience .

        uni:ResearchUnit a uni:Unit .

        uni:West uni:hasUnit uni:ResearchUnit .

        uni:DirectProf a uni:Person ;
            uni:hasName "Direct Professor" ;
            uni:role "Professor of Systems" ;
            uni:worksAt uni:Central .

        uni:NestedProf a uni:Person ;
            uni:hasName "Nested Professor" ;
            uni:role "Professor of Data Science" ;
            uni:worksAt uni:DataDept .

        uni:InverseProf a uni:Person ;
            uni:hasName "Inverse Assistant" ;
            uni:role "Assistant Professor of Robotics" ;
            uni:worksAt uni:ResearchUnit .

        uni:JointProf a uni:Person ;
            uni:hasName "Joint Appointment" ;
            uni:role "Professor of Statistics" ;
            uni:worksAt uni:DataDept, uni:SchoolOfScience .
        """
    )

    actual_pairs = [(str(row.professorName), str(row.universityName)) for row in _run_query(graph)]
    assert set(actual_pairs) == {
        ("Direct Professor", "Central University"),
        ("Inverse Assistant", "West University"),
        ("Joint Appointment", "Central University"),
        ("Nested Professor", "Central University"),
    }
    assert len(actual_pairs) == len(set(actual_pairs))
