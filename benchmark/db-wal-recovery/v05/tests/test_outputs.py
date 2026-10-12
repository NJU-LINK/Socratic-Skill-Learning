from dbwal_assertions import load_output


EXPECTED = [
    {"id": 1, "name": "Alice", "department": "Engineering", "salary": 75000.0},
    {"id": 2, "name": "Bob", "department": "Marketing", "salary": 65000.0},
    {"id": 3, "name": "Charlie", "department": "Finance", "salary": 70000.0},
    {"id": 4, "name": "Diana", "department": "Engineering", "salary": 72000.0},
    {"id": 5, "name": "Eve", "department": "Marketing", "salary": 62000.0},
]


def test_output_is_employee_array():
    data = load_output()
    assert isinstance(data, list)
    assert len(data) == 5


def test_ids_are_complete_unique_and_sorted():
    ids = [row["id"] for row in load_output()]
    assert ids == [1, 2, 3, 4, 5]
    assert len(ids) == len(set(ids))


def test_records_have_exact_schema_and_types():
    for row in load_output():
        assert set(row) == {"id", "name", "department", "salary"}
        assert isinstance(row["id"], int) and not isinstance(row["id"], bool)
        assert isinstance(row["name"], str)
        assert isinstance(row["department"], str)
        assert isinstance(row["salary"], (int, float))


def test_all_names_and_departments_are_correct():
    data = load_output()
    assert [(row["name"], row["department"]) for row in data] == [
        ("Alice", "Engineering"),
        ("Bob", "Marketing"),
        ("Charlie", "Finance"),
        ("Diana", "Engineering"),
        ("Eve", "Marketing"),
    ]


def test_all_salaries_are_correct():
    assert [row["salary"] for row in load_output()] == [75000, 65000, 70000, 72000, 62000]


def test_wal_employee_rows_are_present():
    assert [row["id"] for row in load_output()[-2:]] == [4, 5]


def test_entire_output_is_exact():
    assert load_output() == EXPECTED
