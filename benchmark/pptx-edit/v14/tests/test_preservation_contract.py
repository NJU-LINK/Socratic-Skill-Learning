from pptx_contract import (
    assert_slide_exact,
    assert_slide_with_title_edit,
    load_presentations,
    title_shape_index,
)


ORIGINAL_TO_OUTPUT = [
    (0, 0),
    (1, 1),
    (2, 2),
    (4, 3),
    (6, 4),
    (7, 5),
    (8, 6),
    (9, 7),
    (10, 8),
]


def test_remaining_slides_keep_original_identity_and_order():
    before, after = load_presentations()
    assert len(before.slides) == 11
    assert len(after.slides) == 9
    for original_index, output_index in ORIGINAL_TO_OUTPUT:
        if original_index == 6:
            assert_slide_with_title_edit(
                before.slides[original_index],
                after.slides[output_index],
                allow_bold_change=True,
            )
        else:
            assert_slide_exact(
                before.slides[original_index],
                after.slides[output_index],
            )
    title = after.slides[4].shapes[title_shape_index(after.slides[4])]
    assert title.text.strip() == "深海物种概述"
    runs = [
        run
        for paragraph in title.text_frame.paragraphs
        for run in paragraph.runs
        if run.text
    ]
    assert runs
    assert all(run.font.bold is True for run in runs)
