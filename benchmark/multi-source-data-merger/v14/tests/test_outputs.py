from merger_contract import ContractVerifier


VERIFIER = ContractVerifier(
    {
        "mappings": {
            "source_a": {
                "user_id": "account_id",
                "name": "preferred_name",
                "email": "primary_email",
                "created_date": "signup_date",
                "status": "status_text",
            },
            "source_b": {
                "user_id": "user_key",
                "name": "display_name",
                "email": "contact_email",
                "created_date": "created_on",
                "status": "enabled",
            },
            "source_c": {
                "user_id": "member_id",
                "name": "member_name",
                "email": "email_address",
                "created_date": "joined_at",
                "status": "is_active",
            },
        },
        "date_formats": {
            "source_a": ["%Y/%m/%d"],
            "source_b": ["%Y-%m-%dT%H:%M:%S", "%m/%d/%Y"],
            "source_c": ["%d-%m-%Y", "%Y.%m.%d"],
        },
        "minimum_overlap_users": 8,
        "minimum_backfilled_fields": 0,
        "minimum_conflicts": 14,
    }
)


def test_files_and_schema():
    VERIFIER.assert_files_and_schema()


def test_all_input_users_appear_once():
    VERIFIER.assert_user_coverage()


def test_field_level_priority():
    VERIFIER.assert_merged_content()


def test_output_values_are_normalized():
    VERIFIER.assert_normalized_output()


def test_conflict_report_is_exact():
    VERIFIER.assert_conflicts()


def test_fixture_exercises_dense_overlap_and_conflicts():
    VERIFIER.assert_mechanism_density()
