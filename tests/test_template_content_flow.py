"""Content-editing flow: switching structures must not carry content over.

Display-free tests around the state + model layer that the Control Center's
content editor drives, so the "previous document's content" regression is
locked down without needing a Tk display.
"""
import unittest

from dat.gui.state import (
    GuiState,
    build_preview_content,
    editable_list_tokens,
    structure_toggle_items,
)
from dat.models.screenshot_info import ScreenshotInfo
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


class TestEditingListTokenContent(unittest.TestCase):
    """A `{{test_cases}}` cell expands into rows that have no widget of their
    own, so the list behind it is what the Control Center has to offer."""

    def _template_with_tokens(self) -> DocumentTemplate:
        table = TemplateBlock.create(BLOCK_TABLE)
        table.set_table_size(1, 2)
        table.set_header(0, "S. No.")
        table.set_header(1, "Test Cases")
        table.set_cell(0, 0, "{{index}}")
        table.set_cell(0, 1, "{{test_cases}}")
        bullets = TemplateBlock(kind=BLOCK_BULLET_LIST, items=["{{test_cases}}"])
        return DocumentTemplate(name="T", sections=[
            TemplateSection(title="Test Cases", blocks=[table, bullets])
        ])

    def test_only_referenced_editable_tokens_are_offered(self):
        state = GuiState()
        state.set_active_template(self._template_with_tokens())
        self.assertEqual(editable_list_tokens(state.active_template), ["test_cases"])

    def test_standard_document_offers_no_token_lists(self):
        self.assertEqual(editable_list_tokens(None), [])

    def test_tokens_are_offered_in_panel_order(self):
        template = DocumentTemplate(name="T", sections=[TemplateSection(
            title="S",
            blocks=[TemplateBlock(kind=BLOCK_BULLET_LIST, items=[
                "{{test_cases}}", "{{key_points}}", "{{modules}}",
            ])],
        )])
        # modules is a second spelling of impact_areas, and both land on the
        # one editor rather than two that fight over the same list.
        self.assertEqual(
            editable_list_tokens(template),
            ["key_points", "test_cases", "impact_areas"],
        )

    def test_git_derived_tokens_get_no_editor(self):
        template = DocumentTemplate(name="T", sections=[TemplateSection(
            title="S", blocks=[TemplateBlock(kind=BLOCK_PARAGRAPH, text="{{changed_files}}")],
        )])
        self.assertEqual(editable_list_tokens(template), [])

    def test_editing_test_cases_updates_expanded_rows_and_bullets(self):
        state = GuiState()
        state.set_active_template(self._template_with_tokens())
        state.set_list_token("test_cases", ["Generated case"])
        self.assertIn("Generated case", _rendered(state))

        state.set_list_token("test_cases", ["Edited case", "Added case"])

        rendered = _rendered(state)
        self.assertIn("Edited case", rendered)
        self.assertIn("Added case", rendered)
        self.assertNotIn("Generated case", rendered)

    def test_index_token_renumbers_after_an_edit(self):
        state = GuiState()
        state.set_active_template(self._template_with_tokens())
        state.set_list_token("test_cases", ["One", "Two", "Three"])
        state.set_list_token("test_cases", ["Two", "Three"])

        table = next(b for b in build_preview_content(state) if b.kind == "table")
        self.assertEqual(table.table_rows, [["1", "Two"], ["2", "Three"]])

    def test_dropping_a_test_case_reassigns_its_screenshots(self):
        state = GuiState(screenshots=[ScreenshotInfo(file_path="/tmp/shot.png")])
        state.set_active_template(self._template_with_tokens())
        state.set_list_token("test_cases", ["One", "Two"])
        state.set_screenshot_test_case("/tmp/shot.png", 1)

        state.set_list_token("test_cases", ["One"])

        self.assertIsNone(state.screenshots[0].test_case_index)

    def test_values_round_trip_through_the_editor(self):
        state = GuiState()
        state.set_list_token("key_points", ["A point", "  ", "Another"])
        # Blank rows are how an editor looks mid-typing; they aren't content.
        self.assertEqual(state.list_token_values("key_points"), ["A point", "Another"])
        self.assertTrue(state.summary_user_edited)

    def test_alias_reads_and_writes_the_same_list(self):
        state = GuiState()
        state.set_list_token("modules", ["Checkout"])
        self.assertEqual(state.summary.impact_areas, ["Checkout"])
        self.assertEqual(state.list_token_values("impact_areas"), ["Checkout"])

    def test_unknown_token_is_ignored(self):
        state = GuiState()
        state.set_list_token("changed_files", ["a.py"])
        self.assertEqual(state.list_token_values("changed_files"), [])
        self.assertFalse(state.summary_user_edited)


class TestRowsDefinedWhileBuilding(unittest.TestCase):
    """Rows are optional structure: a table that is the same in every
    document (metadata, say) can carry its rows from the builder, and they
    stay editable and extendable while filling a document in."""

    def _metadata_table(self) -> TemplateBlock:
        table = TemplateBlock.create(BLOCK_TABLE)
        table.set_table_size(2, 2)
        table.set_cell(0, 0, "Ticket No.")
        table.set_cell(0, 1, "{{ticket_id}}")
        table.set_cell(1, 0, "Created By")
        table.set_cell(1, 1, "{{author}}")
        return table

    def _state(self, table: TemplateBlock) -> GuiState:
        state = GuiState(ticket_id="NTRAK-41722", author="Priyansu")
        state.set_active_template(DocumentTemplate(name="T", sections=[
            TemplateSection(title="Task Detail", blocks=[table])
        ]))
        return state

    def test_rows_written_in_the_builder_resolve_per_document(self):
        table = self._metadata_table()
        rendered = _rendered(self._state(table))
        self.assertIn("Ticket No.", rendered)
        self.assertIn("NTRAK-41722", rendered)
        self.assertIn("Priyansu", rendered)
        self.assertNotIn("{{ticket_id}}", rendered)

    def test_builder_rows_survive_saving_and_reloading_the_template(self):
        template = DocumentTemplate(name="T", sections=[
            TemplateSection(title="Task Detail", blocks=[self._metadata_table()])
        ])
        reloaded = DocumentTemplate.from_dict(template.to_dict())
        self.assertEqual(
            reloaded.sections[0].blocks[0].table_rows,
            [["Ticket No.", "{{ticket_id}}"], ["Created By", "{{author}}"]],
        )

    def test_builder_rows_are_editable_while_filling_the_document_in(self):
        table = self._metadata_table()
        state = self._state(table)
        table.set_cell(0, 0, "Ticket")  # what the Control Center's cell entry does
        rendered = _rendered(state)
        self.assertIn("Ticket", rendered)
        self.assertNotIn("Ticket No.", rendered)

    def test_more_rows_can_still_be_added_per_document(self):
        table = self._metadata_table()
        state = self._state(table)
        table.add_row()
        table.set_cell(2, 0, "Approved By")
        table.set_cell(2, 1, "{{approved_by}}")
        state.approved_by = "Reviewer"

        preview = next(b for b in build_preview_content(state) if b.kind == "table")
        self.assertEqual(preview.table_rows[2], ["Approved By", "Reviewer"])

    def test_a_table_can_still_be_left_without_rows(self):
        """The other half of optional: no rows here, all of them per document."""
        table = TemplateBlock.create(BLOCK_TABLE)
        table.set_table_size(0, 2)
        self.assertEqual(table.row_count, 0)
        self.assertTrue(table.add_row())
        self.assertEqual(table.row_count, 1)

    def test_resizing_preserves_rows_that_still_fit(self):
        table = self._metadata_table()
        table.set_table_size(1, 2)
        self.assertEqual(table.table_rows, [["Ticket No.", "{{ticket_id}}"]])


if __name__ == "__main__":
    unittest.main()
