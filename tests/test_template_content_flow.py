"""Content-editing flow: switching structures must not carry content over.

Display-free tests around the state + model layer that the Control Center's
content editor drives, so the "previous document's content" regression is
locked down without needing a Tk display.
"""
import unittest

from dat.gui.state import GuiState, build_preview_content, structure_toggle_items
from dat.models.template_model import (
    BLOCK_BULLET_LIST,
    BLOCK_PARAGRAPH,
    BLOCK_SEPARATOR,
    BLOCK_TABLE,
    FIELD_NOTE,
    DocumentTemplate,
    TemplateBlock,
    TemplateSection,
    content_fields,
    has_editable_content,
    set_content,
)


def _doc(name: str, marker: str) -> DocumentTemplate:
    return DocumentTemplate(name=name, sections=[
        TemplateSection(title=f"{marker} Section", blocks=[
            TemplateBlock(kind=BLOCK_PARAGRAPH, text=f"{marker} CONTENT"),
            TemplateBlock(kind=BLOCK_BULLET_LIST, items=[f"{marker} point"]),
        ]),
        TemplateSection(title=f"{marker} Second", blocks=[
            TemplateBlock(kind=BLOCK_PARAGRAPH, text=f"{marker} SECOND"),
        ]),
    ])


def _rendered(state: GuiState) -> str:
    """Everything the preview would show, flattened for substring checks."""
    parts = []
    for block in build_preview_content(state):
        parts.extend([block.text or "", block.heading or ""])
        parts.extend(block.bullets)
        parts.extend(block.table_headers)
        for row in block.table_rows:
            parts.extend(row)
        parts.extend(block.columns)
    return " | ".join(parts)


class TestSwitchingStructures(unittest.TestCase):
    def test_switching_replaces_all_previous_content(self):
        state = GuiState(ticket_id="X-1", topic="Topic")
        state.set_active_template(_doc("Doc A", "AAA"))
        self.assertIn("AAA CONTENT", _rendered(state))

        state.set_active_template(_doc("Doc B", "BBB"))
        rendered = _rendered(state)
        self.assertIn("BBB CONTENT", rendered)
        self.assertNotIn("AAA", rendered)

    def test_switching_drops_previous_section_toggles(self):
        state = GuiState()
        first = _doc("Doc A", "AAA")
        state.set_active_template(first)
        state.set_template_toggle(first.sections[0].section_id, False)

        second = _doc("Doc B", "BBB")
        state.set_active_template(second)

        self.assertEqual(set(state.template_toggles), {s.section_id for s in second.sections})
        self.assertTrue(all(state.template_toggles.values()))
        self.assertIn("BBB CONTENT", _rendered(state))

    def test_switching_to_standard_document_drops_template_content(self):
        state = GuiState(ticket_id="X-1", topic="Topic")
        state.set_active_template(_doc("Doc A", "AAA"))
        state.set_active_template(None)

        rendered = _rendered(state)
        self.assertNotIn("AAA", rendered)
        self.assertIn("Task Detail", rendered)

    def test_structure_toggles_follow_the_selected_structure(self):
        state = GuiState()
        state.set_active_template(_doc("Doc A", "AAA"))
        self.assertEqual(
            [label for _k, label, _v in structure_toggle_items(state)],
            ["AAA Section", "AAA Second"],
        )

        state.set_active_template(_doc("Doc B", "BBB"))
        self.assertEqual(
            [label for _k, label, _v in structure_toggle_items(state)],
            ["BBB Section", "BBB Second"],
        )

    def test_new_structure_starts_without_previous_document_values(self):
        """Regression: starter() used to seed {{title}}, which resolved to the
        previously open document's title and looked like leaked content."""
        state = GuiState(ticket_id="OLD-1", topic="Previous Feature")
        state.set_active_template(DocumentTemplate.starter())
        self.assertNotIn("Previous Feature", _rendered(state))
        self.assertNotIn("OLD-1", _rendered(state))


class TestEditingActiveStructure(unittest.TestCase):
    def test_editing_a_block_shows_up_in_the_preview(self):
        template = _doc("Doc A", "AAA")
        state = GuiState()
        state.set_active_template(template)

        block = template.sections[0].blocks[0]
        set_content(block, "text", "TYPED BY USER")

        self.assertIn("TYPED BY USER", _rendered(state))
        self.assertNotIn("AAA CONTENT", _rendered(state))

    def test_editing_list_and_table_content(self):
        table = TemplateBlock.create(BLOCK_TABLE)
        template = DocumentTemplate(name="T", sections=[TemplateSection(
            title="S", blocks=[TemplateBlock(kind=BLOCK_BULLET_LIST, items=["old"]), table],
        )])
        state = GuiState()
        state.set_active_template(template)

        set_content(template.sections[0].blocks[0], "items", ["new item"])
        table.set_header(0, "Metric")
        table.set_cell(0, 0, "42")

        rendered = _rendered(state)
        self.assertIn("new item", rendered)
        self.assertIn("Metric", rendered)
        self.assertIn("42", rendered)
        self.assertNotIn("old", rendered)

    def test_hidden_section_content_is_not_rendered_or_offered(self):
        template = _doc("Doc A", "AAA")
        state = GuiState()
        state.set_active_template(template)
        hidden_id = template.sections[1].section_id
        state.set_template_toggle(hidden_id, False)

        self.assertNotIn("AAA SECOND", _rendered(state))
        visible = {s.section_id for s in template.enabled_sections(state.template_toggles)}
        self.assertNotIn(hidden_id, visible)

    def test_rows_added_while_filling_content_reach_the_preview(self):
        """Rows are content: the reader adds as many as needed, like test cases."""
        table = TemplateBlock.create(BLOCK_TABLE)
        table.set_table_size(1, 2)
        table.set_header(0, "Case")
        table.set_header(1, "Status")
        template = DocumentTemplate(name="T", sections=[
            TemplateSection(title="Results", blocks=[table])
        ])
        state = GuiState()
        state.set_active_template(template)

        table.set_cell(0, 0, "First case")
        table.set_cell(0, 1, "Pass")
        table.add_row()
        table.set_cell(1, 0, "Second case")
        table.set_cell(1, 1, "Pass")
        table.add_row()
        table.set_cell(2, 0, "Third case")

        rendered = _rendered(state)
        for expected in ("Case", "Status", "First case", "Second case", "Third case"):
            self.assertIn(expected, rendered)

    def test_removing_rows_updates_the_preview_and_keeps_columns(self):
        table = TemplateBlock.create(BLOCK_TABLE)
        table.set_cell(0, 0, "doomed")
        template = DocumentTemplate(name="T", sections=[
            TemplateSection(title="S", blocks=[table])
        ])
        state = GuiState()
        state.set_active_template(template)
        self.assertIn("doomed", _rendered(state))

        table.remove_row(0)
        rendered = _rendered(state)
        self.assertNotIn("doomed", rendered)
        # Header row (structure) survives an emptied table.
        self.assertIn("Column 1", rendered)
        self.assertEqual(table.col_count, 2)

    def test_empty_table_without_headers_renders_nothing(self):
        table = TemplateBlock.create(BLOCK_TABLE)
        table.include_headers = False
        table.remove_row(0)
        template = DocumentTemplate(name="T", sections=[
            TemplateSection(title="S", show_title=False, blocks=[table])
        ])
        state = GuiState()
        state.set_active_template(template)
        self.assertEqual(build_preview_content(state), [])

    def test_column_count_change_keeps_every_content_row(self):
        table = TemplateBlock.create(BLOCK_TABLE)
        table.add_row()
        table.set_cell(0, 0, "r1")
        table.set_cell(1, 0, "r2")

        # What the builder's Columns stepper does.
        table.set_table_size(table.row_count, 3)

        self.assertEqual(table.row_count, 2)
        self.assertEqual([row[0] for row in table.table_rows], ["r1", "r2"])

    def test_column_weights_reach_the_preview(self):
        table = TemplateBlock.create(BLOCK_TABLE)
        table.set_table_size(1, 3)
        table.set_col_weight(1, 5)
        state = GuiState()
        state.set_active_template(DocumentTemplate(name="T", sections=[
            TemplateSection(title="S", show_title=False, blocks=[table])
        ]))

        block = build_preview_content(state)[0]
        self.assertEqual(block.kind, "table")
        self.assertEqual(block.col_weights, [1, 5, 1])

    def test_preview_weights_stay_aligned_with_the_column_count(self):
        table = TemplateBlock.create(BLOCK_TABLE)
        table.set_col_weight(0, 4)
        state = GuiState()
        state.set_active_template(DocumentTemplate(name="T", sections=[
            TemplateSection(title="S", show_title=False, blocks=[table])
        ]))

        table.set_table_size(table.row_count, 4)
        block = build_preview_content(state)[0]
        self.assertEqual(len(block.col_weights), 4)
        self.assertEqual(len(block.table_headers), 4)

    def test_editable_field_inventory_for_a_mixed_section(self):
        section = TemplateSection(title="S", blocks=[
            TemplateBlock(kind=BLOCK_PARAGRAPH),
            TemplateBlock(kind=BLOCK_BULLET_LIST),
            TemplateBlock.create(BLOCK_TABLE),
            TemplateBlock(kind=BLOCK_SEPARATOR),
        ])
        editable = [b for b in section.blocks if has_editable_content(b)]
        self.assertEqual(len(editable), 3)
        # Inputs only: some blocks also carry FIELD_NOTE explanations (e.g. how
        # {{test_cases}} expands), which are read-only and not fields to fill.
        inputs = [
            f for b in editable for f in content_fields(b) if f.kind != FIELD_NOTE
        ]
        self.assertEqual(len(inputs), 3)


if __name__ == "__main__":
    unittest.main()
