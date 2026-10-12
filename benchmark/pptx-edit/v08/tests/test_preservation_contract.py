from pptx_contract import (
    assert_slide_exact,
    assert_slide_with_title_edit,
    load_presentations,
    title_shape_index,
)


ORIGINAL_TO_OUTPUT = [
    (0, 0),
    (1, 1),
    (3, 2),
    (4, 3),
    (5, 4),
    (6, 5),
    (7, 6),
    (8, 7),
    (9, 8),
    (10, 9),
]


def test_remaining_slides_keep_original_identity_and_order():
    before, after = load_presentations()
    assert len(before.slides) == 11
    assert len(after.slides) == 10
    for original_index, output_index in ORIGINAL_TO_OUTPUT:
        if original_index == 4:
            assert_slide_with_title_edit(
                before.slides[original_index],
                after.slides[output_index],
                allow_bold_change=False,
            )
        else:
            assert_slide_exact(
                before.slides[original_index],
                after.slides[output_index],
            )
    title = after.slides[3].shapes[title_shape_index(after.slides[3])]
    assert title.text.strip() == "Hadal Zone的边界"
