from __future__ import annotations

from email import policy
from email.parser import BytesParser
from pathlib import Path
import sys

import openpyxl
import pytest
from pypdf import PdfReader


DATA = Path("/app/data")
EMAILS = Path("/app/emails")
SOURCE = DATA / "UIC_Admitted_Students.xlsx"

sys.path.insert(0, "/app")
from solve import run


def _applicants() -> list[dict[str, str]]:
    sheet = openpyxl.load_workbook(SOURCE, data_only=True).active
    applicants = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        application_number, last_name, first_name, term, email, _phone = row
        if application_number in (None, ""):
            continue
        applicants.append(
            {
                "application_number": str(application_number),
                "last_name": str(last_name),
                "first_name": str(first_name),
                "term": str(term),
                "email": str(email),
            }
        )
    return applicants


APPLICANTS = _applicants()
COHORTS = [APPLICANTS[index : index + 9] for index in range(0, len(APPLICANTS), 9)]


@pytest.fixture(scope="module", autouse=True)
def _generate_outputs() -> None:
    run()


def _pdf_path(applicant: dict[str, str]) -> Path:
    return DATA / (
        f"{applicant['last_name']}_{applicant['first_name']}_admission.pdf"
    )


def _email_path(applicant: dict[str, str]) -> Path:
    return (
        EMAILS
        / applicant["last_name"]
        / f"{applicant['first_name']}_admission.eml"
    )


def test_pdf_inventory_is_complete_and_exact() -> None:
    expected = {_pdf_path(applicant) for applicant in APPLICANTS}
    actual = set(DATA.glob("*_admission.pdf"))
    assert actual == expected


def test_email_inventory_is_complete_and_exact() -> None:
    expected = {_email_path(applicant) for applicant in APPLICANTS}
    actual = set(EMAILS.rglob("*_admission.eml"))
    assert actual == expected
    assert {
        path.name for path in EMAILS.iterdir() if path.is_dir()
    } == {applicant["last_name"] for applicant in APPLICANTS}


@pytest.mark.parametrize("cohort", COHORTS)
def test_pdf_letters_match_source_rows(cohort: list[dict[str, str]]) -> None:
    for applicant in cohort:
        reader = PdfReader(_pdf_path(applicant))
        assert len(reader.pages) == 1
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        assert "Admission Letter" in text
        assert (
            f"{applicant['first_name']} {applicant['last_name']}"
            in text
        )
        assert applicant["application_number"] in text
        assert applicant["term"] in text
        assert applicant["email"] in text
        assert "admitted" in text.lower()


@pytest.mark.parametrize("cohort", COHORTS)
def test_email_messages_match_source_rows(cohort: list[dict[str, str]]) -> None:
    for applicant in cohort:
        message = BytesParser(policy=policy.default).parsebytes(
            _email_path(applicant).read_bytes()
        )
        assert str(message["From"]) == "admissions@uic.edu"
        assert str(message["To"]) == applicant["email"]
        assert str(message["Subject"]) == (
            f"UIC Admission Decision - {applicant['term']}"
        )
        body_part = message.get_body(preferencelist=("plain",))
        assert body_part is not None
        body = body_part.get_content()
        assert (
            f"{applicant['first_name']} {applicant['last_name']}"
            in body
        )
        assert applicant["application_number"] in body
        assert applicant["term"] in body
        assert "admitted" in body.lower()


def test_run_is_idempotent() -> None:
    before = {
        path.relative_to(Path("/app")): path.read_bytes()
        for root in (DATA, EMAILS)
        for path in root.rglob("*")
        if path.is_file() and path != SOURCE
    }

    run()
    after = {
        path.relative_to(Path("/app")): path.read_bytes()
        for root in (DATA, EMAILS)
        for path in root.rglob("*")
        if path.is_file() and path != SOURCE
    }
    assert after == before
