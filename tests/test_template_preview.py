import unittest

from dat.gui.state import (
    GuiState,
    build_preview_content,
    build_template_blocks,
    structure_toggle_items,
)
from dat.models.doc_request import ChangeSummary
from dat.models.screenshot_info import ScreenshotInfo
from dat.models.template_model import (
    BLOCK_BULLET_LIST,
    BLOCK_CODE,
    BLOCK_HEADING,
    BLOCK_IMAGE,
    BLOCK_PARAGRAPH,
    BLOCK_SCREENSHOTS,
    BLOCK_SEPARATOR,
    BLOCK_SUBHEADING,
    BLOCK_TABLE,
    BLOCK_TWO_COLUMNS,
    DocumentTemplate,
    TemplateBlock,
    TemplateContext,
    TemplateSection,
)


def _template_with(*blocks, title="Section", show_title=True, enabled=True) -> DocumentTemplate:
    section = TemplateSection(title=title, show_title=show_title, enabled=enabled, blocks=list(blocks))
    return DocumentTemplate(name="T", sections=[section])


class TestBuildTemplateBlocks(unittest.TestCase):
    def test_section_title_becomes_level_one_heading(self):
        template = _template_with(TemplateBlock(kind=BLOCK_PARAGRAPH, text="body"), title="Overview")
        blocks = build_template_blocks(template, TemplateContext())

        self.assertEqual([b.kind for b in blocks], ["doc_heading", "paragraph"])
        self.assertEqual(blocks[0].text, "Overview")
        self.assertEqual(blocks[0].level, 1)

    def test_section_title_suppressed_when_show_title_off(self):
        template = _template_with(TemplateBlock(kind=BLOCK_PARAGRAPH, text="body"), show_title=False)
        self.assertEqual([b.kind for b in build_template_blocks(template, TemplateContext())], ["paragraph"])

    def test_disabled_section_is_skipped(self):
        template = _template_with(TemplateBlock(kind=BLOCK_PARAGRAPH, text="hidden"), enabled=False)
        self.assertEqual(build_template_blocks(template, TemplateContext()), [])

    def test_override_can_show_a_disabled_section(self):
        template = _template_with(TemplateBlock(kind=BLOCK_PARAGRAPH, text="x"), enabled=False)
        section_id = template.sections[0].section_id
        blocks = build_template_blocks(template, TemplateContext(), section_overrides={section_id: True})
        self.assertTrue(blocks)

    def test_tokens_resolved_in_every_text_surface(self):
        template = _template_with(
            TemplateBlock(kind=BLOCK_HEADING, text="{{title}}", level=1),
            TemplateBlock(kind=BLOCK_PARAGRAPH, text="Ticket {{ticket_id}}"),
            TemplateBlock(kind=BLOCK_BULLET_LIST, items=["By {{author}}"]),
            TemplateBlock(
                kind=BLOCK_TABLE, table_headers=["{{topic}}"], table_rows=[["{{author}}"]]
            ),
            title="{{ticket_id}} Report",
        )
        context = TemplateContext(title="X-1 Feature", ticket_id="X-1", topic="Feature", author="Dev")
        blocks = build_template_blocks(template, context)

        self.assertEqual(blocks[0].text, "X-1 Report")
        self.assertEqual(blocks[1].text, "X-1 Feature")
        self.assertEqual(blocks[2].text, "Ticket X-1")
        self.assertEqual(blocks[3].bullets, ["By Dev"])
        self.assertEqual(blocks[4].table_headers, ["Feature"])
        self.assertEqual(blocks[4].table_rows, [["Dev"]])

    def test_heading_and_subheading_levels(self):
        template = _template_with(
            TemplateBlock(kind=BLOCK_HEADING, text="H1", level=1),
            TemplateBlock(kind=BLOCK_SUBHEADING, text="Sub", level=1),
            show_title=False,
        )
        blocks = build_template_blocks(template, TemplateContext())
        self.assertEqual(blocks[0].level, 1)
        # A subheading never renders as large as a top-level heading.
        self.assertEqual(blocks[1].level, 2)

    def test_bullet_list_ordered_flag_and_blank_filtering(self):
        block = TemplateBlock(kind=BLOCK_BULLET_LIST, items=["a", "  ", "", "b"], ordered=True)
        blocks = build_template_blocks(_template_with(block, show_title=False), TemplateContext())
        self.assertEqual(blocks[0].bullets, ["a", "b"])
        self.assertTrue(blocks[0].ordered)

    def test_empty_bullet_list_is_dropped(self):
        block = TemplateBlock(kind=BLOCK_BULLET_LIST, items=["", "   "])
        self.assertEqual(build_template_blocks(_template_with(block, show_title=False), TemplateContext()), [])

    def test_table_headers_hidden_when_include_headers_off(self):
        block = TemplateBlock(
            kind=BLOCK_TABLE, table_headers=["A"], table_rows=[["1"]], include_headers=False
        )
        blocks = build_template_blocks(_template_with(block, show_title=False), TemplateContext())
        self.assertEqual(blocks[0].table_headers, [])
        self.assertEqual(blocks[0].table_rows, [["1"]])

    def test_image_without_path_is_dropped(self):
        block = TemplateBlock(kind=BLOCK_IMAGE, caption="no file")
        self.assertEqual(build_template_blocks(_template_with(block, show_title=False), TemplateContext()), [])

    def test_image_with_path_carries_caption(self):
        block = TemplateBlock(kind=BLOCK_IMAGE, image_path="/tmp/a.png", caption="Fig {{ticket_id}}")
        blocks = build_template_blocks(
            _template_with(block, show_title=False), TemplateContext(ticket_id="X-1")
        )
        self.assertEqual(blocks[0].kind, "image")
        self.assertEqual(blocks[0].image_path, "/tmp/a.png")
        self.assertEqual(blocks[0].text, "Fig X-1")

    def test_screenshots_block_groups_by_test_case(self):
        block = TemplateBlock(kind=BLOCK_SCREENSHOTS, text="Evidence")
        shots = [
            ScreenshotInfo(file_path="/tmp/a.png", test_case_index=1),
            ScreenshotInfo(file_path="/tmp/b.png", test_case_index=0),
        ]
        context = TemplateContext(test_cases=["Case A", "Case B"])
        blocks = build_template_blocks(_template_with(block, show_title=False), context, screenshots=shots)

        self.assertEqual(blocks[0].kind, "screenshots")
        self.assertEqual(blocks[0].heading, "Evidence")
        labels = [label for _, label, _ in blocks[0].screenshot_groups]
        self.assertEqual(labels, ["Test Case 1 : Case A", "Test Case 2 : Case B"])

    def test_screenshots_block_dropped_without_screenshots(self):
        block = TemplateBlock(kind=BLOCK_SCREENSHOTS)
        self.assertEqual(build_template_blocks(_template_with(block, show_title=False), TemplateContext()), [])

    def test_code_two_columns_and_separator(self):
        template = _template_with(
            TemplateBlock(kind=BLOCK_CODE, text="print(1)"),
            TemplateBlock(kind=BLOCK_TWO_COLUMNS, columns=["L", "R"]),
            TemplateBlock(kind=BLOCK_SEPARATOR),
            show_title=False,
        )
        blocks = build_template_blocks(template, TemplateContext())
        self.assertEqual([b.kind for b in blocks], ["code", "two_columns", "separator"])
        self.assertEqual(blocks[1].columns, ["L", "R"])


class TestGuiStateTemplateIntegration(unittest.TestCase):
    def test_build_preview_content_uses_template_when_active(self):
        state = GuiState(ticket_id="X-1", topic="Topic")
        state.set_active_template(_template_with(TemplateBlock(kind=BLOCK_PARAGRAPH, text="{{title}}")))

        blocks = build_preview_content(state)
        self.assertEqual([b.kind for b in blocks], ["doc_heading", "paragraph"])
        self.assertEqual(blocks[1].text, "X-1 Topic")

    def test_clearing_template_restores_builtin_layout(self):
        state = GuiState(ticket_id="X-1", topic="Topic")
        state.set_active_template(_template_with(TemplateBlock(kind=BLOCK_PARAGRAPH, text="x")))
        state.set_active_template(None)

        kinds = [b.kind for b in build_preview_content(state)]
        self.assertIn("metadata_table", kinds)
        self.assertFalse(state.uses_custom_template)
        self.assertEqual(state.template_toggles, {})

    def test_template_toggle_hides_section_in_preview(self):
        state = GuiState()
        template = _template_with(TemplateBlock(kind=BLOCK_PARAGRAPH, text="body"))
        state.set_active_template(template)
        section_id = template.sections[0].section_id

        self.assertTrue(build_preview_content(state))
        state.set_template_toggle(section_id, False)
        self.assertEqual(build_preview_content(state), [])

    def test_toggles_seeded_from_saved_section_defaults(self):
        template = DocumentTemplate(name="T", sections=[
            TemplateSection(title="On", enabled=True),
            TemplateSection(title="Off", enabled=False),
        ])
        state = GuiState()
        state.set_active_template(template)
        self.assertEqual(
            [state.template_toggles[s.section_id] for s in template.sections], [True, False]
        )

    def test_resaving_template_keeps_current_toggle_state(self):
        template = _template_with(TemplateBlock(kind=BLOCK_PARAGRAPH, text="body"))
        section_id = template.sections[0].section_id
        state = GuiState()
        state.set_active_template(template)
        state.set_template_toggle(section_id, False)

        # Builder saves the same structure again -> the user's hidden section
        # must stay hidden instead of silently reappearing.
        state.set_active_template(template.copy())
        self.assertFalse(state.template_toggles[section_id])

    def test_structure_toggle_items_builtin(self):
        state = GuiState()
        state.set_toggle("screenshots", False)
        items = structure_toggle_items(state)
        self.assertEqual(items[0][0], "header")
        self.assertEqual(dict((key, value) for key, _label, value in items)["screenshots"], False)

    def test_structure_toggle_items_for_template(self):
        template = DocumentTemplate(name="T", sections=[
            TemplateSection(title="Intro"), TemplateSection(title="Details", enabled=False),
        ])
        state = GuiState()
        state.set_active_template(template)

        items = structure_toggle_items(state)
        self.assertEqual([label for _key, label, _value in items], ["Intro", "Details"])
        self.assertEqual([value for _key, _label, value in items], [True, False])

    def test_template_context_reflects_live_state(self):
        state = GuiState(
            ticket_id="PAY-9", topic="Refunds", author="Dev", approved_by="Lead",
            summary=ChangeSummary(overview="", key_points=["kp"], impact_areas=["Checkout"],
                                  test_cases=["tc"]),
        )
        context = state.template_context()
        self.assertEqual(context.title, "PAY-9 Refunds")
        self.assertEqual(context.ticket_id, "PAY-9")
        self.assertEqual(context.approved_by, "Lead")
        self.assertEqual(context.impact_areas, ["Checkout"])
        self.assertEqual(context.test_cases, ["tc"])


if __name__ == "__main__":
    unittest.main()
