from pathlib import Path

from rdflib import Graph


SOLUTION_PATH = Path("/app/solution.sparql")
GRAPH_PATH = Path("/app/university_graph.ttl")
PREFIXES = "PREFIX uni: <http://university.org/ontology#>\n"


def load_query() -> str:
    assert SOLUTION_PATH.exists(), "Expected /app/solution.sparql to be created"
    query = SOLUTION_PATH.read_text(encoding="utf-8").strip()
    assert query, "solution.sparql is empty"
    return query


def run_query(graph_text: str, query: str):
    graph = Graph()
    graph.parse(data=graph_text, format="turtle")
    return graph.query(query)


def result_pairs(result):
    return {
        (str(row.professorName), str(row.universityName))
        for row in result
    }


def test_query_returns_expected_pairs_for_provided_graph():
    query = load_query()
    graph_text = GRAPH_PATH.read_text(encoding="utf-8")

    results = result_pairs(run_query(graph_text, query))

    expected = {
        ("Martin Keller", "National and Kapodistrian University of Athens"),
        ("Thomas Berger", "National Technical University of Athens"),
        ("John Smith", "Massachusetts Institute of Technology"),
        ("Marie Dubois", "Sorbonne University"),
        ("Alex Morgan", "National Technical University of Athens"),
        ("Felix Wagner", "Instituto Superior Técnico"),
        ("Stefan Mueller", "Ludwig Maximilian University of Munich"),
    }

    assert results == expected


def test_query_handles_broader_professor_titles_semantically():
    query = load_query()
    graph_text = f"""{PREFIXES}
uni:ExampleUniversity a uni:University ;
    uni:hasName "Example University" .

uni:ExampleDepartment a uni:Department ;
    uni:partOfUniversity uni:ExampleUniversity .

uni:AnotherDepartment a uni:Department ;
    uni:partOfUniversity uni:ExampleUniversity .

uni:Alice a uni:Person ;
    uni:hasName "Alice" ;
    uni:role "Professor of Robotics" ;
    uni:worksAt uni:ExampleDepartment ;
    uni:teaches uni:Course1, uni:Course2 .

uni:Bob a uni:Person ;
    uni:hasName "Bob" ;
    uni:role "Assistant Professor of Biology" ;
    uni:worksAt uni:AnotherDepartment .

uni:Carol a uni:Person ;
    uni:hasName "Carol" ;
    uni:role "Associate Professor" ;
    uni:worksAt uni:ExampleDepartment .

uni:Dave a uni:Person ;
    uni:hasName "Dave" ;
    uni:role "Professorial Assistant" ;
    uni:worksAt uni:ExampleDepartment .

uni:Eve a uni:Person ;
    uni:hasName "Eve" ;
    uni:role "Adjunct Lecturer" ;
    uni:worksAt uni:ExampleDepartment .

uni:Course1 a uni:Course .
uni:Course2 a uni:Course .
"""

    results = result_pairs(run_query(graph_text, query))

    assert results == {
        ("Alice", "Example University"),
        ("Bob", "Example University"),
        ("Carol", "Example University"),
    }


def test_query_handles_longer_affiliation_chains_and_direct_university_links():
    query = load_query()
    graph_text = f"""{PREFIXES}
uni:NorthUniversity a uni:University ;
    uni:hasName "North University" .

uni:WestUniversity a uni:University ;
    uni:hasName "West University" .

uni:SchoolOfEngineering a uni:Unit ;
    uni:partOfUniversity uni:NorthUniversity .

uni:ComputerLab a uni:Department ;
    uni:partOf uni:SchoolOfEngineering .

uni:DirectInstitute a uni:University ;
    uni:hasName "West University" .

uni:Farah a uni:Person ;
    uni:hasName "Farah" ;
    uni:role "Full Professor" ;
    uni:worksAt uni:ComputerLab .

uni:Gabe a uni:Person ;
    uni:hasName "Gabe" ;
    uni:role "Research Staff" ;
    uni:worksAt uni:ComputerLab .

uni:Hana a uni:Person ;
    uni:hasName "Hana" ;
    uni:role "Professor of Data Science" ;
    uni:worksAt uni:WestUniversity .
"""

    results = result_pairs(run_query(graph_text, query))

    assert results == {
        ("Farah", "North University"),
        ("Hana", "West University"),
    }


def test_query_projects_exactly_required_variables():
    query = load_query()
    result = run_query(f"""{PREFIXES}
uni:SampleUniversity a uni:University ;
    uni:hasName "Sample University" .

uni:SampleProfessor a uni:Person ;
    uni:hasName "Sample Professor" ;
    uni:role "Full Professor" ;
    uni:worksAt uni:SampleUniversity .
""", query)

    assert [str(variable) for variable in result.vars] == [
        "professorName",
        "universityName",
    ]
