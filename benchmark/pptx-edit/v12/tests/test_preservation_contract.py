from pptx_contract import (
    assert_slide_with_title_edit,
    load_presentations,
)


EXPECTED_TITLE = "Low dimensional and Q-Material fabrication"
EXPECTED_NOTES = (
    "Updated terminology: quantum materials now referred to as Q-Material."
)


def test_only_title_text_and_notes_may_change():
    before, after = load_presentations()
    assert len(before.slides) == len(after.slides) == 1
    assert_slide_with_title_edit(
        before.slides[0],
        after.slides[0],
        allow_bold_change=False,
        allow_notes_change=True,
    )
    assert after.slides[0].shapes[0].text == EXPECTED_TITLE


def test_speaker_notes_are_exact():
    _, after = load_presentations()
    assert after.slides[0].notes_slide.notes_text_frame.text.strip() == EXPECTED_NOTES
