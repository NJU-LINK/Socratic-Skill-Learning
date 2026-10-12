from dbwal_assertions import GREEK_ITEMS, assert_item_schema, load_output


def test_output_is_complete_array():
    data = load_output()
    assert isinstance(data, list)
    assert len(data) == 11


def test_ids_are_complete_unique_and_sorted():
    ids = [row["id"] for row in load_output()]
    assert ids == list(range(1, 12))
    assert len(ids) == len(set(ids))


def test_records_have_exact_schema_and_types():
    assert_item_schema(load_output())


def test_all_names_are_correct():
    assert [row["name"] for row in load_output()] == [row["name"] for row in GREEK_ITEMS]


def test_all_values_are_correct():
    assert [row["value"] for row in load_output()] == [row["value"] for row in GREEK_ITEMS]


def test_rc4_wal_suffix_is_present():
    data = load_output()
    assert data[5:] == GREEK_ITEMS[5:]


def test_entire_output_is_exact():
    assert load_output() == GREEK_ITEMS
