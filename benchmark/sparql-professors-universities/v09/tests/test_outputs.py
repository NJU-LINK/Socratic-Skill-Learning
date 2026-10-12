import os
from pathlib import Path

from rdflib import Graph


GRAPH_PATH = Path(os.environ.get("GRAPH_PATH", "/app/university_graph.ttl"))
QUERY_PATH = Path(os.environ.get("QUERY_PATH", "/app/solution.sparql"))


def _load_results():
    graph = Graph()
    graph.parse(GRAPH_PATH, format="turtle")
    query_text = QUERY_PATH.read_text()
    rows = graph.query(query_text)
    return sorted((str(row.professorName), str(row.universityName)) for row in rows)


def _run_query_on_turtle(turtle_text):
    graph = Graph()
    graph.parse(data=turtle_text, format="turtle")
    query_text = QUERY_PATH.read_text()
    rows = graph.query(query_text)
    return sorted((str(row.professorName), str(row.universityName)) for row in rows)


def test_query_file_exists_and_uses_required_variables():
    query_text = QUERY_PATH.read_text()

    assert "?professorName" in query_text
    assert "?universityName" in query_text
    assert "SELECT DISTINCT ?professorName ?universityName" in " ".join(query_text.split())


def test_query_returns_expected_professor_university_pairs():
    results = _load_results()

    assert results == [
        ("Nathan Cole", "University of California, Berkeley"),
        ("Martin Keller", "National and Kapodistrian University of Athens"),
        ("Thomas Berger", "National Technical University of Athens"),
        ("Nadia Fischer", "Instituto Superior Técnico"),
        ("John Smith", "Massachusetts Institute of Technology"),
        ("Marie Dubois", "Sorbonne University"),
        ("Alex Morgan", "National Technical University of Athens"),
        ("Stefan Mueller", "Ludwig Maximilian University of Munich"),
    ]


def test_query_deduplicates_cross_appointments():
    results = _load_results()

    assert len(results) == len(set(results))
    assert results.count(("Alex Morgan", "National Technical University of Athens")) == 1
    assert results.count(("Nathan Cole", "University of California, Berkeley")) == 1
    assert results.count(("Nadia Fischer", "Instituto Superior Técnico")) == 1


def test_query_includes_memberof_affiliations_and_excludes_non_professors():
    results = set(_load_results())

    assert ("Thomas Berger", "National Technical University of Athens") in results
    assert ("Martin Keller", "National and Kapodistrian University of Athens") in results
    assert ("Jane Petterson", "University of California, Berkeley") not in results
    assert ("Mike Wazowski", "National Technical University of Athens") not in results


def test_query_handles_memberof_only_affiliation_path():
    results = _run_query_on_turtle(
        """
        @prefix uni: <http://university.org/ontology#> .

        uni:OnlyMemberUniversity a uni:University ;
            uni:hasName "Only Member University" .

        uni:OnlyMemberInstitute a uni:Institute ;
            uni:partOfUniversity uni:OnlyMemberUniversity .

        uni:DirectUniversity a uni:University ;
            uni:hasName "Direct University" .

        uni:DirectDepartment a uni:Department ;
            uni:partOfUniversity uni:DirectUniversity .

        uni:MemberOnlyProfessor a uni:Person ;
            uni:hasName "Member Only Professor" ;
            uni:role "Assistant Professor of Data Science" ;
            uni:memberOf uni:OnlyMemberInstitute .

        uni:WorksAtProfessor a uni:Person ;
            uni:hasName "Works At Professor" ;
            uni:role "Professor of Robotics" ;
            uni:worksAt uni:DirectDepartment .

        uni:MemberOnlyStaff a uni:Person ;
            uni:hasName "Member Only Staff" ;
            uni:role "Research Staff" ;
            uni:memberOf uni:OnlyMemberInstitute .
        """
    )

    assert results == [
        ("Member Only Professor", "Only Member University"),
        ("Works At Professor", "Direct University"),
    ]
