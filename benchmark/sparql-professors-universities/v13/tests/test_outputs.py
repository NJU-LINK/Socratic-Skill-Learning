from sparql_test_support import load_query, query_rows


def test_query_matches_variant_graph():
    variables, rows = query_rows()

    assert variables == ["professorName", "universityName"]
    assert set(rows) == {
        ("Alex Morgan", "National Technical University of Athens"),
        ("Thomas Berger", "National Technical University of Athens"),
        ("Felix Wagner", "Instituto Superior Técnico"),
        ("Martin Keller", "National and Kapodistrian University of Athens"),
        ("John Smith", "Massachusetts Institute of Technology"),
        ("Marie Dubois", "Sorbonne University"),
        ("Stefan Mueller", "Ludwig Maximilian University of Munich"),
    }


def test_query_uses_role_and_rank_signals_without_duplicate_rows():
    _, rows = query_rows(
        turtle_text="""
        @prefix uni: <http://university.org/ontology#> .
        uni:U a uni:University ; uni:hasName "Alpha University" .
        uni:D a uni:Department ; uni:partOfUniversity uni:U .

        uni:FullProfessorRank a uni:AcademicRank ; uni:rankLabel "Professor" .
        uni:AssistantProfessorRank a uni:AcademicRank ;
            uni:rankLabel "Assistant Professor" .
        uni:LecturerRank a uni:AcademicRank ; uni:rankLabel "Lecturer" .
        uni:PostdoctoralResearcherRank a uni:AcademicRank ;
            uni:rankLabel "Postdoctoral Researcher" .

        uni:RoleOnly a uni:Person ;
            uni:hasName "Role Only" ;
            uni:role "Professor of Logic" ;
            uni:worksAt uni:D .
        uni:RankOnly a uni:Person ;
            uni:hasName "Rank Only" ;
            uni:hasAcademicRank uni:AssistantProfessorRank ;
            uni:worksAt uni:D .
        uni:Both a uni:Person ;
            uni:hasName "Both Signals" ;
            uni:role "Assistant Professor of AI" ;
            uni:hasAcademicRank uni:AssistantProfessorRank ;
            uni:worksAt uni:D .
        uni:Lecturer a uni:Person ;
            uni:hasName "Lecturer Person" ;
            uni:role "Lecturer in Computing" ;
            uni:hasAcademicRank uni:LecturerRank ;
            uni:worksAt uni:D .
        uni:Postdoc a uni:Person ;
            uni:hasName "Postdoc Person" ;
            uni:hasAcademicRank uni:PostdoctoralResearcherRank ;
            uni:worksAt uni:D .
        """
    )

    assert set(rows) == {
        ("Role Only", "Alpha University"),
        ("Rank Only", "Alpha University"),
        ("Both Signals", "Alpha University"),
    }
    assert len(rows) == 3


def test_query_traverses_mixed_affiliation_chains():
    _, rows = query_rows(
        turtle_text="""
        @prefix uni: <http://university.org/ontology#> .
        uni:U a uni:University ; uni:hasName "Deeply Nested University" .
        uni:Consortium a uni:Consortium ; uni:affiliatedWithUniversity uni:U .
        uni:School a uni:School ; uni:partOf uni:Consortium .
        uni:Institute a uni:Institute ; uni:partOfUniversity uni:School .
        uni:Lab a uni:Lab ; uni:belongsToUniversity uni:Institute .
        uni:AssistantProfessorRank a uni:AcademicRank ;
            uni:rankLabel "Assistant Professor" .
        uni:Person a uni:Person ;
            uni:hasName "Deep Chain Prof" ;
            uni:hasAcademicRank uni:AssistantProfessorRank ;
            uni:worksAt uni:Lab .
        """
    )

    assert rows == [("Deep Chain Prof", "Deeply Nested University")]


def test_query_resists_duplicate_producing_graph_noise():
    _, rows = query_rows(
        turtle_text="""
        @prefix uni: <http://university.org/ontology#> .
        uni:U a uni:University ; uni:hasName "Duplicate University" .
        uni:D a uni:Department ; uni:partOfUniversity uni:U .
        uni:AssistantProfessorRank a uni:AcademicRank ;
            uni:rankLabel "Assistant Professor" .
        uni:P a uni:Person ;
            uni:hasName "Noisy Professor" ;
            uni:role "Assistant Professor of Data Science" ;
            uni:hasAcademicRank uni:AssistantProfessorRank ;
            uni:worksAt uni:D ;
            uni:profileKeyword "graphs", "databases", "knowledge representation" ;
            uni:researchArea uni:A1, uni:A2, uni:A3 .
        uni:A1 a uni:ResearchArea .
        uni:A2 a uni:ResearchArea .
        uni:A3 a uni:ResearchArea .
        """
    )

    assert rows == [("Noisy Professor", "Duplicate University")]


def test_query_is_not_seed_answer_literal_enumeration():
    query = load_query().lower()
    assert "values" not in query
    assert "orfeas menis" not in query
    assert "sorbonne university" not in query
