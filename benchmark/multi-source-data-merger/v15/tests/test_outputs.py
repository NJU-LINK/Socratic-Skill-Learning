from merger_contract import ContractVerifier


VERIFIER = ContractVerifier(
    {
        "mappings": {
            "source_a": {
                "user_id": "member_ref",
                "name": "display_name",
                "email": "contact_email",
                "created_date": "signup_day",
                "status": "account_state",
            },
            "source_b": {
                "user_id": "person_id",
                "name": "legal_name",
                "email": "email_contact",
                "created_date": "created_ts",
                "status": "lifecycle",
            },
            "source_c": {
                "user_id": "uid",
                "name": "preferred_name",
                "email": "mail",
                "created_date": "joined_on",
                "status": "enabled_flag",
            },
        },
        "name_mode": "title",
        "email_mode": "lower",
        "minimum_overlap_users": 4,
        "minimum_backfilled_fields": 9,
        "minimum_conflicts": 2,
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


def test_fixture_exercises_overlap_conflict_and_sparse_backfill():
    VERIFIER.assert_mechanism_density()
