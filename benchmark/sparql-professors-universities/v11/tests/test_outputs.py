from sparql_test_support import query_rows


def test_query_matches_variant_graph():
    variables, rows = query_rows()

    assert variables == ["professorName", "universityName"]
    assert sorted(rows) == [
        ("Nathan Cole", "University of California, Berkeley"),
        ("Martin Keller", "National and Kapodistrian University of Athens"),
        ("Thomas Berger", "National Technical University of Athens"),
        ("John Smith", "Massachusetts Institute of Technology"),
        ("Marie Dubois", "Sorbonne University"),
        ("Alex Morgan", "National Technical University of Athens"),
        ("Felix Wagner", "Instituto Superior Tecnico"),
        ("Stefan Mueller", "Ludwig Maximilian University of Munich"),
    ]


def test_query_applies_the_declared_rank_policy():
    _, rows = query_rows(
        turtle_text="""
        @prefix uni: <http://university.org/ontology#> .
        uni:North a uni:University ; uni:hasName "North University" .
        uni:Computing a uni:Department ; uni:linkedTo uni:North .

        uni:Ada a uni:Person ;
            uni:hasName "Ada Byron" ;
            uni:role "Professor of Logic" ;
            uni:worksAt uni:Computing .
        uni:Grace a uni:Person ;
            uni:hasName "Grace Hopper" ;
            uni:role "Assistant Professor in Robotics" ;
            uni:worksAt uni:Computing .
        uni:Edsger a uni:Person ;
            uni:hasName "Edsger Dijkstra" ;
            uni:role "Associate Professor" ;
            uni:worksAt uni:Computing .
        uni:Barbara a uni:Person ;
            uni:hasName "Barbara Liskov" ;
            uni:role "Adjunct Professor" ;
            uni:worksAt uni:Computing .
        uni:Donald a uni:Person ;
            uni:hasName "Donald Knuth" ;
            uni:role "Senior Lecturer" ;
            uni:worksAt uni:Computing .
        """
    )

    assert set(rows) == {
        ("Ada Byron", "North University"),
        ("Grace Hopper", "North University"),
    }


def test_query_handles_bounded_organizational_paths_and_deduplicates():
    _, rows = query_rows(
        turtle_text="""
        @prefix uni: <http://university.org/ontology#> .
        uni:West a uni:University ; uni:hasName "West University" .
        uni:School a uni:School ; uni:partOfInstitution uni:West .
        uni:Dept a uni:Department ;
            uni:belongsTo uni:School ;
            uni:alsoBelongsTo uni:West .
        uni:Group a uni:ResearchGroup ;
            uni:within uni:Dept ;
            uni:reportsThrough uni:School .

        uni:Lin a uni:Person ;
            uni:hasName "Lin Alvarez" ;
            uni:role "Full Professor" ;
            uni:worksAt uni:Group .
        uni:Kim a uni:Person ;
            uni:hasName "Kim Nguyen" ;
            uni:role "Assistant Professor" ;
            uni:worksAt uni:Group .
        uni:Pat a uni:Person ;
            uni:hasName "Pat Rivera" ;
            uni:role "Professor" ;
            uni:worksAt uni:West .
        uni:Casey a uni:Person ;
            uni:hasName "Casey Jones" ;
            uni:role "Visiting Professor" ;
            uni:worksAt uni:Group .
        """
    )

    assert sorted(rows) == [
        ("Kim Nguyen", "West University"),
        ("Lin Alvarez", "West University"),
        ("Pat Rivera", "West University"),
    ]
