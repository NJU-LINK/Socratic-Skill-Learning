from merger_contract import ContractVerifier


VERIFIER = ContractVerifier(
    {
        "mappings": {
            "source_a": {
                "user_id": "acct_id",
                "name": "preferred_name",
                "email": "contact_email",
                "created_date": "registered_on",
                "status": "member_state",
            },
            "source_b": {
                "user_id": "user_ref",
                "name": "display_label",
                "email": "email_address",
                "created_date": "created_at",
                "status": "lifecycle",
            },
            "source_c": {
                "user_id": "userId",
                "name": "fullName",
                "email": "email",
                "created_date": "joined_on",
                "status": "status_flag",
            },
        },
        "minimum_overlap_users": 6,
        "minimum_backfilled_fields": 14,
        "minimum_conflicts": 5,
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

