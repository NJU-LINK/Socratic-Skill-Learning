from pathlib import Path

from rdflib import Graph


QUERY_PATH = Path("/app/solution.sparql")
GRAPH_PATH = Path("/app/university_graph.ttl")


def load_query() -> str:
    assert QUERY_PATH.exists(), "/app/solution.sparql was not created"
    query = QUERY_PATH.read_text(encoding="utf-8").strip()
    assert query, "/app/solution.sparql is empty"
    return query


def query_rows(*, turtle_text: str | None = None):
    graph = Graph()
    if turtle_text is None:
        assert GRAPH_PATH.exists(), "/app/university_graph.ttl is missing"
        graph.parse(GRAPH_PATH, format="turtle")
    else:
        graph.parse(data=turtle_text, format="turtle")

    results = graph.query(load_query())
    variables = [str(variable) for variable in results.vars]
    rows = [
        (str(row.professorName), str(row.universityName))
        for row in results
    ]
    return variables, rows
