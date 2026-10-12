from pptx_contract import (
    assert_slide_exact,
    assert_slide_with_title_edit,
    load_presentations,
    title_shape_index,
)


def test_all_non_target_slides_are_exactly_preserved():
    before, after = load_presentations()
    assert len(after.slides) == len(before.slides)
    for index in range(1, len(before.slides)):
        assert_slide_exact(before.slides[index], after.slides[index])


def test_target_slide_changed_only_in_title_text_and_bold():
    before, after = load_presentations()
    assert_slide_with_title_edit(
        before.slides[0],
        after.slides[0],
        allow_bold_change=True,
    )
    title = after.slides[0].shapes[title_shape_index(after.slides[0])]
    assert title.text.strip() == "Deep Sea Exploration"
    runs = [
        run
        for paragraph in title.text_frame.paragraphs
        for run in paragraph.runs
        if run.text
    ]
    assert runs
    assert all(run.font.bold is True for run in runs)
