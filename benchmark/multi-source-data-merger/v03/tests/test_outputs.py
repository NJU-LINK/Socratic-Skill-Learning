from merger_contract import ContractVerifier


VERIFIER = ContractVerifier(
    {
        "mappings": {
            "source_a": {
                "user_id": "id",
                "name": "full_name",
                "email": "email",
                "created_date": "registration_date",
                "status": "status",
            },
            "source_b": {
                "user_id": "user_id",
                "name": "name",
                "email": "email_address",
                "created_date": "created_at",
                "status": "is_active",
            },
            "source_c": {
                "user_id": "userId",
                "name": "userName",
                "email": "email",
                "created_date": "joined",
                "status": "active",
            },
        },
        "minimum_overlap_users": 3,
        "minimum_backfilled_fields": 2,
        "minimum_conflicts": 3,
    }
)


def test_files_and_schema():
    VERIFIER.assert_files_and_schema()


def test_all_input_users_appear_once():
    VERIFIER.assert_user_coverage()


def test_field_level_priority_and_backfill():
    VERIFIER.assert_merged_content()


def test_output_values_are_normalized():
    VERIFIER.assert_normalized_output()


def test_conflict_report_is_exact():
    VERIFIER.assert_conflicts()


def test_fixture_exercises_overlap_conflict_and_backfill():
    VERIFIER.assert_mechanism_density()

