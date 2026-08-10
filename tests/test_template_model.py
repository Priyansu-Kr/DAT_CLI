import unittest

from dat.models.template_model import (
    BLOCK_BULLET_LIST,
    BLOCK_HEADING,
    BLOCK_PARAGRAPH,
    BLOCK_IMAGE,
    BLOCK_SCREENSHOTS,
    BLOCK_SEPARATOR,
    BLOCK_TABLE,
    BLOCK_TWO_COLUMNS,
    BLOCK_SPEC_BY_KIND,
    FIELD_LINE,
    FIELD_LIST,
    FIELD_MULTILINE,
    FIELD_NOTE,
    FIELD_PATH,
    FIELD_TABLE,
    DEFAULT_TABLE_ROWS,
    MAX_COL_WEIGHT,
    MAX_TABLE_COLS,
    MAX_TABLE_ROWS,
    MIN_COL_WEIGHT,
    SCHEMA_VERSION,
    DocumentTemplate,
    TemplateBlock,
    TemplateContext,
    TemplateError,
    TemplateSection,
    content_fields,
    get_content,
    has_editable_content,
    set_content,
)


class TestTemplateBlock(unittest.TestCase):
    def test_create_covers_every_palette_kind(self):
        for kind in BLOCK_SPEC_BY_KIND:
            block = TemplateBlock.create(kind)
            self.assertEqual(block.kind, kind)
            self.assertTrue(block.block_id)

    def test_create_rejects_unknown_kind(self):
        with self.assertRaises(TemplateError):
            TemplateBlock.create("hologram")

    def test_table_starts_with_one_content_row(self):
        """Rows are content, so a new table opens with a single empty row."""
        block = TemplateBlock.create(BLOCK_TABLE)
        self.assertEqual(block.row_count, DEFAULT_TABLE_ROWS)
        self.assertEqual(block.col_count, 2)
        self.assertTrue(all(len(row) == 2 for row in block.table_rows))

    def test_set_table_size_preserves_content_and_clamps(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        block.set_cell(0, 0, "keep me")

        block.set_table_size(4, 3)
        self.assertEqual(block.row_count, 4)
        self.assertEqual(block.col_count, 3)
        self.assertEqual(block.table_rows[0][0], "keep me")
        self.assertEqual(len(block.table_headers), 3)

        block.set_table_size(1, 1)
        self.assertEqual(block.row_count, 1)
        self.assertEqual(block.col_count, 1)
        self.assertEqual(block.table_rows[0][0], "keep me")

        block.set_table_size(0, MAX_TABLE_COLS + 5)
        self.assertEqual(block.row_count, 0)  # a table may hold no rows yet
        self.assertEqual(block.col_count, MAX_TABLE_COLS)

    def test_add_row_appends_blank_row_of_the_right_width(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        block.set_table_size(1, 3)

        self.assertTrue(block.add_row())
        self.assertEqual(block.row_count, 2)
        self.assertEqual(block.table_rows[-1], ["", "", ""])

    def test_add_row_at_index(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        block.set_cell(0, 0, "first")
        block.add_row(index=0)
        self.assertEqual(block.table_rows[1][0], "first")
        self.assertEqual(block.table_rows[0][0], "")

    def test_add_row_stops_at_the_cap(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        block.set_table_size(MAX_TABLE_ROWS, 2)
        self.assertFalse(block.add_row())
        self.assertEqual(block.row_count, MAX_TABLE_ROWS)

    def test_remove_row(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        block.set_table_size(3, 2)
        block.set_cell(1, 0, "middle")

        self.assertTrue(block.remove_row(1))
        self.assertEqual(block.row_count, 2)
        self.assertNotIn("middle", [cell for row in block.table_rows for cell in row])

    def test_remove_row_rejects_bad_index(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        self.assertFalse(block.remove_row(-1))
        self.assertFalse(block.remove_row(99))

    def test_all_rows_can_be_removed(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        while block.row_count:
            self.assertTrue(block.remove_row(0))
        self.assertEqual(block.row_count, 0)
        # Columns are structural, so they survive an empty table.
        self.assertEqual(block.col_count, 2)

    def test_row_count_survives_a_column_change(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        block.add_row()
        block.add_row()
        block.set_table_size(block.row_count, 4)
        self.assertEqual(block.row_count, 3)
        self.assertTrue(all(len(row) == 4 for row in block.table_rows))

    def test_columns_share_evenly_by_default(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        self.assertEqual(block.normalized_col_weights(), [1, 1])
        self.assertEqual(block.col_width_percentages(), [50, 50])
        self.assertTrue(block.uses_equal_columns())

    def test_set_col_weight_changes_the_split(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        block.set_table_size(1, 3)
        block.set_col_weight(0, 1)
        block.set_col_weight(1, 4)
        block.set_col_weight(2, 1)

        self.assertEqual(block.normalized_col_weights(), [1, 4, 1])
        self.assertEqual(block.col_width_percentages(), [17, 67, 17])
        self.assertFalse(block.uses_equal_columns())
        self.assertAlmostEqual(sum(block.col_width_fractions()), 1.0, places=6)

    def test_col_weight_is_clamped(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        block.set_col_weight(0, MAX_COL_WEIGHT + 50)
        block.set_col_weight(1, -3)
        self.assertEqual(block.normalized_col_weights(), [MAX_COL_WEIGHT, MIN_COL_WEIGHT])

    def test_set_col_weight_rejects_out_of_range_column(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        self.assertFalse(block.set_col_weight(9, 3))
        self.assertFalse(block.set_col_weight(-1, 3))

    def test_weights_follow_a_column_count_change(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        block.set_table_size(1, 3)
        block.set_col_weight(1, 5)

        block.set_table_size(1, 4)  # added column takes an even share
        self.assertEqual(block.normalized_col_weights(), [1, 5, 1, 1])

        block.set_table_size(1, 2)  # dropped column drops its weight
        self.assertEqual(block.normalized_col_weights(), [1, 5])

    def test_weights_survive_serialisation(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        block.set_table_size(1, 3)
        block.set_col_weight(2, 6)
        restored = TemplateBlock.from_dict(block.to_dict())
        self.assertEqual(restored.normalized_col_weights(), [1, 1, 6])

    def test_malformed_stored_weights_are_repaired(self):
        for stored, expected in (
            ([], [1, 1]),                      # missing
            ([3], [3, 1]),                     # too short
            ([2, 2, 9, 9], [2, 2]),            # too long
            (["x", 4], [1, 4]),                # unparseable entry dropped
            ("nonsense", [1, 1]),              # wrong type entirely
        ):
            block = TemplateBlock.from_dict({
                "kind": BLOCK_TABLE,
                "table_headers": ["A", "B"],
                "table_rows": [["1", "2"]],
                "col_weights": stored,
            })
            self.assertEqual(block.normalized_col_weights(), expected, stored)

    def test_rows_roundtrip_including_empty_table(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        block.remove_row(0)
        restored = TemplateBlock.from_dict(block.to_dict())
        self.assertEqual(restored.row_count, 0)
        self.assertEqual(restored.col_count, 2)

    def test_clone_gets_new_id_and_independent_data(self):
        block = TemplateBlock.create(BLOCK_BULLET_LIST)
        clone = block.clone()
        self.assertNotEqual(block.block_id, clone.block_id)
        clone.items.append("extra")
        self.assertNotEqual(block.items, clone.items)

    def test_roundtrip_keeps_kind_specific_fields(self):
        block = TemplateBlock.create(BLOCK_TABLE)
        block.set_cell(1, 1, "value")
        block.include_headers = False
        restored = TemplateBlock.from_dict(block.to_dict())
        self.assertEqual(restored.table_rows, block.table_rows)
        self.assertFalse(restored.include_headers)

    def test_from_dict_normalises_ragged_table(self):
        restored = TemplateBlock.from_dict({
            "kind": BLOCK_TABLE,
            "table_headers": ["A", "B", "C"],
            "table_rows": [["1"], ["1", "2", "3", "4"]],
        })
        self.assertEqual(restored.col_count, 3)
        self.assertTrue(all(len(row) == 3 for row in restored.table_rows))


class TestTemplateSection(unittest.TestCase):
    def test_move_block_respects_bounds(self):
        section = TemplateSection(title="S")
        first = section.add_block(TemplateBlock.create(BLOCK_HEADING))
        second = section.add_block(TemplateBlock.create(BLOCK_PARAGRAPH))

        self.assertFalse(section.move_block(first.block_id, -1))
        self.assertTrue(section.move_block(first.block_id, 1))
        self.assertEqual([b.block_id for b in section.blocks], [second.block_id, first.block_id])

    def test_add_block_at_index(self):
        section = TemplateSection()
        a = section.add_block(TemplateBlock.create(BLOCK_HEADING))
        b = section.add_block(TemplateBlock.create(BLOCK_PARAGRAPH), index=0)
        self.assertEqual([blk.block_id for blk in section.blocks], [b.block_id, a.block_id])

    def test_remove_block(self):
        section = TemplateSection()
        block = section.add_block(TemplateBlock.create(BLOCK_HEADING))
        self.assertTrue(section.remove_block(block.block_id))
        self.assertFalse(section.remove_block(block.block_id))


class TestDocumentTemplate(unittest.TestCase):
    def test_starter_is_never_empty(self):
        template = DocumentTemplate.starter()
        self.assertTrue(template.sections)
        self.assertTrue(template.block_count)

    def test_enabled_sections_honours_overrides(self):
        template = DocumentTemplate(name="T")
        visible = template.add_section(TemplateSection(title="Visible"))
        hidden = template.add_section(TemplateSection(title="Hidden", enabled=False))

        self.assertEqual([s.section_id for s in template.enabled_sections()], [visible.section_id])
        overridden = template.enabled_sections({visible.section_id: False, hidden.section_id: True})
        self.assertEqual([s.section_id for s in overridden], [hidden.section_id])

    def test_move_section(self):
        template = DocumentTemplate()
        first = template.add_section(TemplateSection(title="A"))
        second = template.add_section(TemplateSection(title="B"))
        self.assertTrue(template.move_section(second.section_id, -1))
        self.assertEqual([s.title for s in template.sections], ["B", "A"])
        self.assertFalse(template.move_section(second.section_id, -1))

    def test_serialisation_roundtrip(self):
        template = DocumentTemplate.starter("My Doc")
        template.add_section(TemplateSection(title="Tables", blocks=[TemplateBlock.create(BLOCK_TABLE)]))
        restored = DocumentTemplate.from_dict(template.to_dict())

        self.assertEqual(restored.name, "My Doc")
        self.assertEqual(restored.template_id, template.template_id)
        self.assertEqual(len(restored.sections), len(template.sections))
        self.assertEqual(restored.block_count, template.block_count)
        self.assertEqual(template.to_dict()["schema_version"], SCHEMA_VERSION)

    def test_from_dict_rejects_newer_schema(self):
        data = DocumentTemplate.starter().to_dict()
        data["schema_version"] = SCHEMA_VERSION + 1
        with self.assertRaises(TemplateError):
            DocumentTemplate.from_dict(data)

    def test_from_dict_rejects_non_object(self):
        with self.assertRaises(TemplateError):
            DocumentTemplate.from_dict(["not", "a", "template"])

    def test_from_dict_skips_unknown_block_kinds(self):
        data = {
            "schema_version": SCHEMA_VERSION,
            "name": "Forward compatible",
            "sections": [{
                "title": "S",
                "blocks": [{"kind": BLOCK_PARAGRAPH, "text": "kept"}, {"kind": "future_widget"}],
            }],
        }
        template = DocumentTemplate.from_dict(data)
        self.assertEqual(template.block_count, 1)
        self.assertEqual(template.sections[0].blocks[0].text, "kept")

    def test_from_dict_repairs_duplicate_ids(self):
        data = {
            "sections": [
                {"section_id": "dup", "title": "A", "blocks": [{"block_id": "b", "kind": BLOCK_PARAGRAPH}]},
                {"section_id": "dup", "title": "B", "blocks": [{"block_id": "b", "kind": BLOCK_PARAGRAPH}]},
            ]
        }
        template = DocumentTemplate.from_dict(data)
        ids = [s.section_id for s in template.sections]
        self.assertEqual(len(set(ids)), 2)
        block_ids = [b.block_id for s in template.sections for b in s.blocks]
        self.assertEqual(len(set(block_ids)), 2)

    def test_duplicate_creates_fresh_identity(self):
        template = DocumentTemplate.starter("Original")
        clone = template.duplicate()

        self.assertNotEqual(clone.template_id, template.template_id)
        self.assertEqual(clone.name, "Original (Copy)")
        original_ids = {s.section_id for s in template.sections}
        self.assertFalse(original_ids & {s.section_id for s in clone.sections})

    def test_copy_is_deep(self):
        template = DocumentTemplate.starter()
        clone = template.copy()
        clone.sections[0].title = "Changed"
        self.assertNotEqual(template.sections[0].title, "Changed")

    def test_locate_block(self):
        template = DocumentTemplate.starter()
        block = template.sections[0].blocks[0]
        found = template.locate_block(block.block_id)
        self.assertIsNotNone(found)
        self.assertEqual(found[1].block_id, block.block_id)
        self.assertIsNone(template.locate_block("missing"))


class TestEditableContentSchema(unittest.TestCase):
    def test_every_palette_kind_has_a_schema(self):
        for kind in BLOCK_SPEC_BY_KIND:
            block = TemplateBlock.create(kind)
            fields = content_fields(block)
            self.assertIsInstance(fields, list)
            for field in fields:
                self.assertIn(field.kind, {
                    FIELD_LINE, FIELD_MULTILINE, FIELD_LIST, FIELD_TABLE, FIELD_PATH, FIELD_NOTE,
                })

    def test_separator_has_no_editable_content(self):
        block = TemplateBlock.create(BLOCK_SEPARATOR)
        self.assertEqual(content_fields(block), [])
        self.assertFalse(has_editable_content(block))

    def test_content_bearing_kinds_are_editable(self):
        for kind in (BLOCK_HEADING, BLOCK_PARAGRAPH, BLOCK_BULLET_LIST, BLOCK_TABLE):
            self.assertTrue(has_editable_content(TemplateBlock.create(kind)), kind)

    def test_screenshots_note_is_not_counted_as_editable_input(self):
        block = TemplateBlock.create(BLOCK_SCREENSHOTS)
        notes = [f for f in content_fields(block) if f.kind == FIELD_NOTE]
        self.assertEqual(len(notes), 1)
        self.assertTrue(has_editable_content(block))  # the heading line is editable

    def test_get_and_set_simple_field(self):
        block = TemplateBlock.create(BLOCK_PARAGRAPH)
        set_content(block, "text", "hello")
        self.assertEqual(get_content(block, "text"), "hello")
        self.assertEqual(block.text, "hello")

    def test_set_items_coerces_to_strings(self):
        block = TemplateBlock.create(BLOCK_BULLET_LIST)
        set_content(block, "items", ["a", 2])
        self.assertEqual(block.items, ["a", "2"])

    def test_two_column_keys_map_onto_columns(self):
        block = TemplateBlock.create(BLOCK_TWO_COLUMNS)
        set_content(block, "columns.0", "left side")
        set_content(block, "columns.1", "right side")
        self.assertEqual(block.columns, ["left side", "right side"])
        self.assertEqual(get_content(block, "columns.0"), "left side")

    def test_column_write_pads_missing_slots(self):
        block = TemplateBlock(kind=BLOCK_TWO_COLUMNS, columns=[])
        set_content(block, "columns.1", "only right")
        self.assertEqual(block.columns, ["", "only right"])

    def test_get_missing_column_returns_empty(self):
        block = TemplateBlock(kind=BLOCK_TWO_COLUMNS, columns=[])
        self.assertEqual(get_content(block, "columns.0"), "")

    def test_unknown_field_key_raises(self):
        block = TemplateBlock.create(BLOCK_PARAGRAPH)
        with self.assertRaises(TemplateError):
            set_content(block, "not_a_field", "x")

    def test_edited_content_survives_serialisation(self):
        block = TemplateBlock.create(BLOCK_PARAGRAPH)
        set_content(block, "text", "typed in the control center")
        restored = TemplateBlock.from_dict(block.to_dict())
        self.assertEqual(restored.text, "typed in the control center")


class TestStarterTemplate(unittest.TestCase):
    def test_starter_carries_no_tokens(self):
        """A brand-new structure must not show the previous document's title."""
        template = DocumentTemplate.starter()
        for section in template.sections:
            self.assertNotIn("{{", section.title)
            for block in section.blocks:
                self.assertNotIn("{{", block.text)

    def test_starter_has_editable_content(self):
        template = DocumentTemplate.starter()
        self.assertTrue(any(has_editable_content(b) for s in template.sections for b in s.blocks))


class TestReferencedTokens(unittest.TestCase):
    def test_no_tokens_in_a_plain_template(self):
        template = DocumentTemplate.starter()
        self.assertEqual(template.referenced_tokens(), set())

    def test_finds_tokens_in_every_text_surface(self):
        table = TemplateBlock.create(BLOCK_TABLE)
        table.set_header(0, "{{topic}}")
        table.set_cell(0, 1, "signed off by {{approved_by}}")
        template = DocumentTemplate(name="T", sections=[
            TemplateSection(title="{{ticket_id}} report", blocks=[
                TemplateBlock(kind=BLOCK_HEADING, text="{{title}}"),
                TemplateBlock(kind=BLOCK_PARAGRAPH, text="Written by {{author}}"),
                TemplateBlock(kind=BLOCK_BULLET_LIST, items=["as of {{date}}"]),
                TemplateBlock(kind=BLOCK_TWO_COLUMNS, columns=["{{branch}}", ""]),
                TemplateBlock(kind=BLOCK_IMAGE, image_path="/tmp/a.png", caption="{{modules}}"),
                table,
            ]),
        ])
        self.assertEqual(
            template.referenced_tokens(),
            {"ticket_id", "title", "author", "date", "branch", "modules", "topic", "approved_by"},
        )

    def test_token_lookup_is_case_and_space_insensitive(self):
        template = DocumentTemplate(name="T", sections=[TemplateSection(
            title="S", blocks=[TemplateBlock(kind=BLOCK_PARAGRAPH, text="{{ Author }} and {{APPROVED_BY}}")],
        )])
        self.assertEqual(template.referenced_tokens(), {"author", "approved_by"})

    def test_unknown_tokens_are_reported_as_written(self):
        template = DocumentTemplate(name="T", sections=[TemplateSection(
            title="S", blocks=[TemplateBlock(kind=BLOCK_PARAGRAPH, text="{{not_a_token}}")],
        )])
        self.assertEqual(template.referenced_tokens(), {"not_a_token"})
        self.assertNotIn("author", template.referenced_tokens())

    def test_hidden_sections_still_count(self):
        """A section switched off is still part of the document."""
        template = DocumentTemplate(name="T", sections=[TemplateSection(
            title="S", enabled=False,
            blocks=[TemplateBlock(kind=BLOCK_PARAGRAPH, text="{{author}}")],
        )])
        self.assertIn("author", template.referenced_tokens())


class TestTemplateContext(unittest.TestCase):
    def test_resolves_known_tokens(self):
        context = TemplateContext(title="PAY-1 Checkout", ticket_id="PAY-1", author="Dev")
        self.assertEqual(context.resolve("{{title}} by {{author}}"), "PAY-1 Checkout by Dev")

    def test_token_matching_is_case_and_space_insensitive(self):
        context = TemplateContext(ticket_id="X-9")
        self.assertEqual(context.resolve("{{ Ticket_Id }}"), "X-9")

    def test_unknown_tokens_are_left_visible(self):
        context = TemplateContext()
        self.assertEqual(context.resolve("{{nope}}"), "{{nope}}")

    def test_resolve_handles_none_and_empty(self):
        context = TemplateContext()
        self.assertEqual(context.resolve(None), "")
        self.assertEqual(context.resolve(""), "")

    def test_list_tokens_are_joined(self):
        context = TemplateContext(impact_areas=["Checkout", "Cart"])
        self.assertEqual(context.resolve("{{modules}}"), "Checkout, Cart")


if __name__ == "__main__":
    unittest.main()
