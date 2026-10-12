import json
import os
import re

OUTPUT_PATH = "/app/recover.json"


def test_output_exists():
    """The recover.json file must exist."""
    assert os.path.exists(OUTPUT_PATH), f"{OUTPUT_PATH} does not exist"


def test_output_is_valid_json():
    """The output must be valid JSON."""
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    assert isinstance(data, list), "Output must be a JSON array"


def test_output_is_non_empty():
    """At least some records must be recovered."""
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    assert len(data) >= 400, (
        f"Expected at least 400 recovered records, got {len(data)}"
    )


def test_record_format():
    """Each record must have 'word' and 'data' keys with string values."""
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    for i, record in enumerate(data):
        assert isinstance(record, dict), f"Record {i} is not a dict"
        assert "word" in record, f"Record {i} missing 'word' key"
        assert "data" in record, f"Record {i} missing 'data' key"
        assert isinstance(record["word"], str), f"Record {i} 'word' is not a string"
        assert isinstance(record["data"], str), f"Record {i} 'data' is not a string"


def test_word_pattern():
    """Each word must follow the pattern item_NNNN (4-digit numeric suffix)."""
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    word_re = re.compile(r"^item_\d{4}$")
    for record in data:
        assert word_re.match(record["word"]), (
            f"Word '{record['word']}' does not match pattern item_NNNN"
        )


def test_no_zeroed_page_records():
    """Records from zeroed pages (rowids 1-6) must not appear."""
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    for record in data:
        rid = int(record["word"].split("_")[1])
        assert rid >= 7, (
            f"Record {record['word']} is from zeroed pages (rowid < 7)"
        )


def test_word_matches_data_prefix():
    """The data field must start with payload_row_{NNNN}_ matching the word."""
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    for record in data:
        rid = int(record["word"].split("_")[1])
        expected_prefix = f"payload_row_{rid:04d}_"
        assert record["data"].startswith(expected_prefix), (
            f"Record {record['word']} data does not start with {expected_prefix}"
        )


def test_data_periodic_pattern():
    """The data must follow the periodic pattern: prefix + 60 A's repeated."""
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    PERIOD = 77
    for record in data:
        rid = int(record["word"].split("_")[1])
        expected_prefix = f"payload_row_{rid:04d}_"
        text = record["data"]
        assert len(expected_prefix) == 17, (
            f"Unexpected prefix length for {record['word']}"
        )
        expected_block = expected_prefix + "A" * 60
        expected_text = (
            expected_block * (len(text) // PERIOD)
            + expected_block[: len(text) % PERIOD]
        )
        assert text == expected_text, (
            f"Record {record['word']} data does not match expected periodic pattern"
        )


def test_records_are_sorted():
    """Records must be sorted by their numeric suffix."""
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    rowids = [int(r["word"].split("_")[1]) for r in data]
    assert rowids == sorted(rowids), "Records are not sorted by rowid"


def test_no_duplicate_words():
    """No two records should have the same word."""
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    words = [r["word"] for r in data]
    assert len(words) == len(set(words)), "Duplicate word values found"


def test_data_length_reasonable():
    """Data lengths should be in a reasonable range (1KB-6KB)."""
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    for record in data:
        dlen = len(record["data"])
        assert 1000 <= dlen <= 6000, (
            f"Record {record['word']} has unexpected data length {dlen}"
        )


def test_all_recoverable_records_present():
    """All records with rowids 7-500 should be present."""
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    rowids = {int(r["word"].split("_")[1]) for r in data}
    missing = set(range(7, 501)) - rowids
    assert len(missing) == 0, f"Missing recoverable records: {sorted(missing)}"
