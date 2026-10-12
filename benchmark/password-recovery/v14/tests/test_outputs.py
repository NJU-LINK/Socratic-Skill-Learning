import hashlib
import os
import re
from pathlib import Path

APP_ROOT = Path(os.environ.get("TBENCH_APP_ROOT", "/app"))
SNAPSHOT_ROOT = Path(os.environ.get("TBENCH_SNAPSHOT_ROOT", "/opt/task-input"))
EVIDENCE_ROOT = APP_ROOT / "varsea"
OUTPUT_FILE = APP_ROOT / "recovered_passwords.txt"
EVIDENCE_BASELINE = SNAPSHOT_ROOT / "evidence.sha256"
TREE_BASELINE = SNAPSHOT_ROOT / "app_tree_baseline.txt"

# Public evidence declared in the task instruction.
EXPECTED_SHA256 = "79464fe0e46675e38329f5e4f59dc6a4c91ce300f70f2dd99610cadcb135e32f"
PASSWORD_SHAPE = re.compile(r"[A-Z0-9]{10}")
FRAG_LINE = re.compile(r"FRAG\s+(\d+)\s+(\d+)\s+(\d+)")


def recovered_lines() -> list[str]:
    assert OUTPUT_FILE.is_file(), f"{OUTPUT_FILE} does not exist"
    return [
        line.strip()
        for line in OUTPUT_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def evidence_baseline() -> dict[str, str]:
    assert EVIDENCE_BASELINE.is_file(), f"{EVIDENCE_BASELINE} does not exist"
    entries = {}
    for line in EVIDENCE_BASELINE.read_text(encoding="utf-8").splitlines():
        digest, rel = line.split(maxsplit=1)
        entries[rel.strip()] = digest
    assert entries, "evidence baseline is empty"
    return entries


def test_output_file_exists():
    assert recovered_lines(), f"{OUTPUT_FILE} has no candidate lines"


def test_exactly_one_candidate_is_emitted():
    lines = recovered_lines()
    assert len(lines) == 1, f"expected exactly one verified candidate, found {len(lines)}"


def test_candidate_matches_public_shape_constraints():
    password = recovered_lines()[0]
    assert PASSWORD_SHAPE.fullmatch(password), (
        f"candidate is not exactly 10 uppercase-letter/digit characters: {password!r}"
    )


def test_exact_recovery_against_public_hash():
    password = recovered_lines()[0]
    digest = hashlib.sha256(password.encode()).hexdigest()
    assert digest == EXPECTED_SHA256, "candidate does not match the declared SHA-256 hash"


def test_evidence_tree_structure_is_intact():
    baseline = evidence_baseline()
    on_disk = {
        str(path.relative_to(EVIDENCE_ROOT))
        for path in EVIDENCE_ROOT.rglob("*")
        if path.is_file()
    }
    missing = set(baseline) - on_disk
    added = on_disk - set(baseline)
    assert not missing, f"evidence files removed: {sorted(missing)}"
    assert not added, f"new files appeared in the evidence tree: {sorted(added)}"

    images = [rel for rel in baseline if rel.endswith(".dat")]
    assert len(images) >= 2, "expected multiple disk images in the evidence tree"
    for rel in images:
        fragmap = EVIDENCE_ROOT / (rel + ".fragmap")
        assert fragmap.is_file(), f"missing sibling fragment map for {rel}"
        entries = [
            (int(seq), int(offset), int(length))
            for seq, offset, length in FRAG_LINE.findall(
                fragmap.read_text(encoding="utf-8")
            )
        ]
        assert len(entries) >= 3, f"{fragmap} declares fewer than 3 fragments"
        seqs = [seq for seq, _, _ in entries]
        assert len(set(seqs)) == len(seqs), f"duplicate fragment seq values in {fragmap}"
        image_size = (EVIDENCE_ROOT / rel).stat().st_size
        for _, offset, length in entries:
            assert 0 <= offset and length > 0 and offset + length <= image_size, (
                f"fragment entry out of image bounds in {fragmap}"
            )


def test_evidence_bytes_are_unchanged():
    for rel, digest in evidence_baseline().items():
        current = hashlib.sha256((EVIDENCE_ROOT / rel).read_bytes()).hexdigest()
        assert current == digest, f"evidence file was modified: {rel}"


def test_no_side_effects_under_app():
    assert TREE_BASELINE.is_file(), f"{TREE_BASELINE} does not exist"
    baseline = set(TREE_BASELINE.read_text(encoding="utf-8").splitlines())
    current = {
        str(path.relative_to(APP_ROOT))
        for path in APP_ROOT.rglob("*")
        if path.is_file()
    }
    allowed_new = {"recovered_passwords.txt"}
    assert current - baseline <= allowed_new, (
        f"unexpected new files under {APP_ROOT}: {sorted(current - baseline - allowed_new)}"
    )
    assert baseline - current == set(), (
        f"files deleted under {APP_ROOT}: {sorted(baseline - current)}"
    )
