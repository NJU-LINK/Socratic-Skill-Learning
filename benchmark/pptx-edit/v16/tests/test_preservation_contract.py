from pptx_contract import (
    assert_slide_exact,
    assert_slide_with_title_edit,
    load_presentations,
)


EXPECTED_NOTES = "Updated title and removed redundant slide."
ORIGINAL_TO_OUTPUT = [
    (0, 0),
    (1, 1),
    (2, 2),
    (4, 3),
    (5, 4),
    (6, 5),
    (7, 6),
    (8, 7),
    (9, 8),
    (10, 9),
]


def test_surviving_slides_keep_original_identity_and_order():
    before, after = load_presentations()
    assert len(before.slides) == 11
    assert len(after.slides) == 10
    for original_index, output_index in ORIGINAL_TO_OUTPUT:
        if original_index == 0:
            assert_slide_with_title_edit(
                before.slides[original_index],
                after.slides[output_index],
                allow_bold_change=True,
                allow_notes_change=True,
            )
        else:
            assert_slide_exact(
                before.slides[original_index],
                after.slides[output_index],
            )


def test_title_and_notes_are_exact():
    _, after = load_presentations()
    title = next(
        shape
        for shape in after.slides[0].shapes
        if shape.has_text_frame and shape.text.strip() == "深海探索"
    )
    runs = [
        run
        for paragraph in title.text_frame.paragraphs
        for run in paragraph.runs
    ]
    assert runs
    assert all(run.font.bold is True for run in runs)
    assert after.slides[0].notes_slide.notes_text_frame.text.strip() == EXPECTED_NOTES
