from dbwal_assertions import assert_item_schema, load_output


EXPECTED = [
    {
        "id": index,
        "name": f"item{index}",
        "value": {1: 999, 2: 888, 3: 333, 4: 222}.get(index, index * 10),
    }
    for index in range(1, 61)
]


def test_output_is_complete_array():
    data = load_output()
    assert isinstance(data, list)
    assert len(data) == 60


def test_ids_are_complete_unique_and_sorted():
    ids = [row["id"] for row in load_output()]
    assert ids == list(range(1, 61))
    assert len(ids) == len(set(ids))


def test_records_have_exact_schema_and_types():
    assert_item_schema(load_output())
    assert all(isinstance(row["value"], int) and not isinstance(row["value"], bool) for row in load_output())


def test_all_names_are_correct():
    assert [row["name"] for row in load_output()] == [f"item{index}" for index in range(1, 61)]


def test_all_values_are_correct():
    assert [row["value"] for row in load_output()] == [row["value"] for row in EXPECTED]


def test_conflicting_updates_use_primary_wal_precedence():
    data = {row["id"]: row for row in load_output()}
    assert [data[index]["value"] for index in range(1, 5)] == [999, 888, 333, 222]


def test_both_wal_stream_suffixes_are_present():
    data = {row["id"]: row for row in load_output()}
    assert [data[index]["value"] for index in range(51, 56)] == [510, 520, 530, 540, 550]
    assert [data[index]["value"] for index in range(56, 61)] == [560, 570, 580, 590, 600]


def test_entire_output_is_exact():
    assert load_output() == EXPECTED
