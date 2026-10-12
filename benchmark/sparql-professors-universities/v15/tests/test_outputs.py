from sparql_test_support import query_rows


def test_query_matches_variant_graph():
    variables, rows = query_rows()

    assert variables == ["professorName", "universityName"]
    assert set(rows) == {
        ("Nathan Cole", "University of California, Berkeley"),
        ("Martin Keller", "National and Kapodistrian University of Athens"),
        ("Thomas Berger", "National Technical University of Athens"),
        ("John Smith", "Massachusetts Institute of Technology"),
        ("Marie Dubois", "Sorbonne University"),
        ("Alex Morgan", "National Technical University of Athens"),
        ("Felix Wagner", "Instituto Superior Tecnico"),
        ("Stefan Mueller", "Ludwig Maximilian University of Munich"),
    }
    assert len(rows) == 8


def test_query_prefers_work_affiliation_over_teaching_affiliation():
    _, rows = query_rows(
        turtle_text="""
        @prefix uni: <http://university.org/ontology#> .
        uni:WorkU a uni:University ; uni:hasName "Work University" .
        uni:TeachU a uni:University ; uni:hasName "Teaching University" .
        uni:WorkDept a uni:Department ; uni:partOfUniversity uni:WorkU .
        uni:TeachDept a uni:Department ; uni:partOfUniversity uni:TeachU .
        uni:Course a uni:Course ; uni:isTaughtIn uni:TeachDept .
        uni:Person a uni:Person ;
            uni:hasName "Casey Rao" ;
            uni:role "Assistant Professor of Systems" ;
            uni:worksAt uni:WorkDept ;
            uni:teaches uni:Course .
        """
    )

    assert rows == [("Casey Rao", "Work University")]


def test_query_uses_course_fallback_and_deduplicates_courses():
    _, rows = query_rows(
        turtle_text="""
        @prefix uni: <http://university.org/ontology#> .
        uni:U a uni:University ; uni:hasName "Only University" .
        uni:D a uni:Department ; uni:partOfUniversity uni:U .
        uni:A a uni:Course ; uni:isTaughtIn uni:D .
        uni:B a uni:Course ; uni:isTaughtIn uni:D .
        uni:Person a uni:Person ;
            uni:hasName "Riley Chen" ;
            uni:role "Professor of Data Science" ;
            uni:teaches uni:A, uni:B .
        """
    )

    assert rows == [("Riley Chen", "Only University")]


def test_query_excludes_non_professors_on_both_affiliation_paths():
    _, rows = query_rows(
        turtle_text="""
        @prefix uni: <http://university.org/ontology#> .
        uni:U a uni:University ; uni:hasName "Example University" .
        uni:D a uni:Department ; uni:partOfUniversity uni:U .
        uni:C a uni:Course ; uni:isTaughtIn uni:D .
        uni:Lecturer a uni:Person ;
            uni:hasName "Lecturer" ;
            uni:role "Senior Lecturer" ;
            uni:worksAt uni:D .
        uni:Staff a uni:Person ;
            uni:hasName "Staff" ;
            uni:role "Research Staff" ;
            uni:teaches uni:C .
        uni:Student a uni:Person ;
            uni:hasName "Student" ;
            uni:role "Graduate Student" ;
            uni:teaches uni:C .
        """
    )

    assert rows == []
