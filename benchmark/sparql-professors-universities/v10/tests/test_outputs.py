import unicodedata

from sparql_test_support import load_query, query_rows


EXPECTED_ROWS = {
    ("Martin Keller", "National and Kapodistrian University of Athens"),
    ("Thomas Berger", "National Technical University of Athens"),
    ("Elena Garcia", "Universidad Politecnica de Madrid"),
    ("John Smith", "Massachusetts Institute of Technology"),
    ("Marie Dubois", "Sorbonne University"),
    ("Noah Brooks", "ETH Zurich"),
    ("Alex Morgan", "National Technical University of Athens"),
    ("Felix Wagner", "Instituto Superior Tecnico"),
    ("Stefan Mueller", "Ludwig Maximilian University of Munich"),
}


def normalized(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def normalized_rows(rows):
    return {(normalized(name), normalized(university)) for name, university in rows}


def test_query_has_exact_projection_and_seed_results():
    variables, rows = query_rows()

    assert variables == ["professorName", "universityName"]
    assert normalized_rows(rows) == EXPECTED_ROWS
    assert len(rows) == len(EXPECTED_ROWS)


def test_query_is_not_a_hardcoded_answer_list():
    query = load_query()
    assert "values" not in query.lower()
    for row in EXPECTED_ROWS:
        for literal in row:
            assert literal not in query


def test_query_handles_role_meaning_and_multi_hop_affiliation():
    variables, rows = query_rows(
        turtle_text="""
        @prefix uni: <http://university.org/ontology#> .

        uni:NorthshoreU a uni:University ;
            uni:hasName "Northshore University" .
        uni:CoastalU a uni:University ;
            uni:hasName "Coastal State University" .
        uni:GlobalU a uni:University ;
            uni:hasName "Global Institute of Technology" .

        uni:EngineeringDivision a uni:Division ;
            uni:partOfUniversity uni:NorthshoreU .
        uni:AIInstitute a uni:Department ;
            uni:subOrganizationOf uni:EngineeringDivision ;
            uni:affiliatedWith uni:NorthshoreU .
        uni:LawSchool a uni:School .
        uni:CoastalU uni:hasFaculty uni:LawSchool .

        uni:Ada a uni:Person ;
            uni:hasName "Ada Lovelace" ;
            uni:role "Endowed Professor of Computer Science" ;
            uni:worksAt uni:AIInstitute .
        uni:Sam a uni:Person ;
            uni:hasName "Sam Rivera" ;
            uni:role "Clinical Associate Professor in Medicine" ;
            uni:worksAt uni:LawSchool .
        uni:Ivy a uni:Person ;
            uni:hasName "Ivy Chen" ;
            uni:role "Professor Emeritus" ;
            uni:worksAt uni:GlobalU .
        uni:Omar a uni:Person ;
            uni:hasName "Omar Haddad" ;
            uni:role "Adjunct Professor" ;
            uni:worksAt uni:AIInstitute .

        uni:Rita a uni:Person ;
            uni:hasName "Rita Moss" ;
            uni:role "Professor Search Coordinator" ;
            uni:worksAt uni:AIInstitute .
        uni:Leo a uni:Person ;
            uni:hasName "Leo Grant" ;
            uni:role "Assistant to the Professor" ;
            uni:worksAt uni:LawSchool .
        uni:Mina a uni:Person ;
            uni:hasName "Mina Patel" ;
            uni:role "Teaching Professor Program Administrator" ;
            uni:worksAt uni:AIInstitute .
        """
    )

    assert variables == ["professorName", "universityName"]
    assert set(rows) == {
        ("Ada Lovelace", "Northshore University"),
        ("Sam Rivera", "Coastal State University"),
        ("Ivy Chen", "Global Institute of Technology"),
        ("Omar Haddad", "Northshore University"),
    }
    assert len(rows) == 4


def test_query_deduplicates_equivalent_paths():
    _, rows = query_rows(
        turtle_text="""
        @prefix uni: <http://university.org/ontology#> .
        uni:U a uni:University ; uni:hasName "Example University" .
        uni:School a uni:School ; uni:partOfUniversity uni:U .
        uni:Dept a uni:Department ;
            uni:partOf uni:School ;
            uni:affiliatedWith uni:U .
        uni:Person a uni:Person ;
            uni:hasName "Taylor Kim" ;
            uni:role "Assistant Professor" ;
            uni:worksAt uni:Dept .
        """
    )

    assert rows == [("Taylor Kim", "Example University")]
