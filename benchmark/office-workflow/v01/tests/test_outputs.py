from __future__ import annotations

import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest


sys.path.insert(0, "/app")
from solve import run


EMAIL_ROOT = Path("/app/data/emails/Bob")
OUTPUT = Path("/app/data/answer.txt")
TARGET_SUBJECTS = {"scheduled meeting", "application approved"}


def _messages() -> list[tuple[str, str]]:
    messages: list[tuple[str, str]] = []
    for path in sorted(EMAIL_ROOT.glob("*.eml")):
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        body_part = message.get_body(preferencelist=("plain",))
        messages.append(
            (
                str(message["Subject"]),
                body_part.get_content().strip() if body_part is not None else "",
            )
        )
    return messages


def test_answer_exists_and_is_nonempty() -> None:
    run()
    assert OUTPUT.exists()
    assert OUTPUT.read_text(encoding="utf-8").strip()


def test_answer_has_exact_selected_messages_in_filename_order() -> None:
    run()
    selected = [
        f"Subject: {subject}\n{body}"
        for subject, body in _messages()
        if subject in TARGET_SUBJECTS
    ]
    assert OUTPUT.read_text(encoding="utf-8") == "\n\n".join(selected) + "\n"


@pytest.mark.parametrize(
    ("subject", "body"),
    [message for message in _messages() if message[0] in TARGET_SUBJECTS],
)
def test_selected_message_subject_and_body_are_preserved(subject: str, body: str) -> None:
    run()
    output = OUTPUT.read_text(encoding="utf-8")
    assert subject in output
    assert body in output


@pytest.mark.parametrize(
    ("subject", "body"),
    [message for message in _messages() if message[0] not in TARGET_SUBJECTS],
)
def test_distractor_message_is_excluded(subject: str, body: str) -> None:
    run()
    output = OUTPUT.read_text(encoding="utf-8")
    assert subject not in output
    assert body not in output
