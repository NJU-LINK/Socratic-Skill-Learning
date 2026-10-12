from __future__ import annotations

import sys
import re
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest
from pypdf import PdfReader


sys.path.insert(0, "/app")
from solve import run


APP = Path("/app")


def _cases() -> list[tuple[Path, str]]:
    cases: list[tuple[Path, str]] = []
    for source in sorted((APP / "data/emails").rglob("*.eml")):
        message = BytesParser(policy=policy.default).parsebytes(source.read_bytes())
        recipient = str(message["To"]).split("@", 1)[0]
        body_part = message.get_body(preferencelist=("plain",))
        body = body_part.get_content().strip() if body_part is not None else ""
        first_body_line = next(line for line in body.splitlines() if line.strip())
        cases.append(
            (
                APP / "data" / recipient / f"{source.stem}.pdf",
                first_body_line,
            )
        )
    return cases


def test_pdf_inventory_is_exactly_one_output_per_source_email() -> None:
    run()
    expected = {output for output, _ in _cases()}
    actual = {
        path
        for directory in APP.joinpath("data").iterdir()
        if directory.is_dir() and directory.name != "emails"
        for path in directory.rglob("*.pdf")
    }
    assert actual == expected


@pytest.mark.parametrize(
    ("output", "body_line"),
    _cases(),
    ids=[output.relative_to(APP).as_posix() for output, _ in _cases()],
)
def test_each_email_is_routed_to_a_readable_pdf(output: Path, body_line: str) -> None:
    run()
    assert output.exists()
    text = " ".join(page.extract_text() or "" for page in PdfReader(output).pages)
    normalized_text = re.sub(r"\s+", " ", text).strip()
    normalized_body = re.sub(r"\s+", " ", body_line).strip()
    assert normalized_body in normalized_text
