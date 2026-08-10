"""Tokens a custom template can use, and the two that pull in real data.

The gap this covers: `test_cases` was carried in the render context but never
exposed as a token, so a user-built template had no way to show the test cases
Gemini (or an MCP agent) wrote - and a Code Block could only hold code typed by
hand, even though the branch diff was sitting right there.
"""
import unittest

from dat.models.template_model import (
    BLOCK_BULLET_LIST,
    BLOCK_CODE,
    BLOCK_TABLE,
    CODE_TOKEN_MAX_FILES,
    CODE_TOKENS,
    LIST_TOKENS,
    SUPPORTED_TOKENS,
    TemplateContext,
    added_code_from_diff,
    content_fields,
    diff_excerpt,
)

DIFF = """diff --git a/app/SyncService.kt b/app/SyncService.kt
--- a/app/SyncService.kt
+++ b/app/SyncService.kt
@@ -10,6 +10,9 @@
 class SyncService {
+    fun sync(): Boolean {
+        return repository.push()
+    }
-    fun oldSync() {}
diff --git a/app/Main.kt b/app/Main.kt
--- a/app/Main.kt
+++ b/app/Main.kt
@@ -1,2 +1,3 @@
+import app.SyncService
"""


def context(**kwargs) -> TemplateContext:
    defaults = dict(
        title="NTRAK-1 Add Sync",
        test_cases=["Sync completes offline", "Retry after failure"],
        key_points=["SyncService.kt: added sync()"],
        changed_files=["app/SyncService.kt", "app/Main.kt"],
        raw_diff=DIFF,
    )
    defaults.update(kwargs)
    return TemplateContext(**defaults)


class TestTokensExist(unittest.TestCase):
    def test_the_previously_missing_tokens_are_offered(self):
        for name in ("test_cases", "test_recommendations", "changed_files",
                     "code_changes", "code_diff"):
            self.assertIn(name, SUPPORTED_TOKENS)

    def test_test_cases_resolves_inline(self):
        self.assertEqual(
            context().resolve("Cases: {{test_cases}}"),
            "Cases: Sync completes offline, Retry after failure",
        )

    def test_unknown_token_is_still_left_visible(self):
        self.assertEqual(context().resolve("{{nope}}"), "{{nope}}")

    def test_list_and_code_groups_do_not_overlap(self):
        self.assertFalse(set(LIST_TOKENS) & set(CODE_TOKENS))


class TestListExpansion(unittest.TestCase):
    def test_a_lone_list_token_becomes_one_bullet_per_entry(self):
        items = context().resolve_items(["Intro", "{{test_cases}}"])
        self.assertEqual(
            items, ["Intro", "Sync completes offline", "Retry after failure"]
        )

    def test_a_token_mixed_with_text_stays_inline(self):
        items = context().resolve_items(["Covers {{test_cases}}"])
        self.assertEqual(items, ["Covers Sync completes offline, Retry after failure"])

    def test_an_empty_list_contributes_nothing(self):
        """No API key means no test cases - the document should not carry a
        blank bullet where they would have been."""
        items = context(test_cases=[]).resolve_items(["{{test_cases}}", "Written by hand"])
        self.assertEqual(items, ["Written by hand"])

    def test_whitespace_around_the_token_still_expands(self):
        self.assertEqual(len(context().resolve_items([" {{ test_cases }} "])), 2)

    def test_changed_files_expands_without_any_ai(self):
        items = context(test_cases=[]).resolve_items(["{{changed_files}}"])
        self.assertEqual(items, ["app/SyncService.kt", "app/Main.kt"])


class TestTableRowExpansion(unittest.TestCase):
    def test_a_row_with_a_list_token_becomes_one_row_per_entry(self):
        rows = context().resolve_rows([["{{index}}", "{{test_cases}}", "Success"]])
        self.assertEqual(rows, [
            ["1", "Sync completes offline", "Success"],
            ["2", "Retry after failure", "Success"],
        ])

    def test_other_rows_are_untouched(self):
        rows = context().resolve_rows([["Ticket", "{{title}}"]])
        self.assertEqual(rows, [["Ticket", "NTRAK-1 Add Sync"]])

    def test_no_entries_means_no_rows(self):
        rows = context(test_cases=[]).resolve_rows([["{{index}}", "{{test_cases}}", "Success"]])
        self.assertEqual(rows, [])

    def test_index_outside_an_expanding_row_stays_visible(self):
        """It has nothing to count there, so it must not silently blank out."""
        rows = context().resolve_rows([["{{index}}", "{{title}}"]])
        self.assertEqual(rows, [["{{index}}", "NTRAK-1 Add Sync"]])


class TestCodeFromTheDiff(unittest.TestCase):
    def test_code_changes_is_the_added_source_without_diff_markers(self):
        code = added_code_from_diff(DIFF)

        self.assertIn("fun sync(): Boolean {", code)
        self.assertIn("return repository.push()", code)
        self.assertNotIn("+    fun sync", code)      # '+' stripped
        self.assertNotIn("oldSync", code)            # removals aren't new code
        self.assertNotIn("@@", code)

    def test_each_file_is_labelled(self):
        code = added_code_from_diff(DIFF)
        self.assertIn("==== app/SyncService.kt ====", code)
        self.assertIn("==== app/Main.kt ====", code)

    def test_code_diff_keeps_patch_form(self):
        patch = diff_excerpt(DIFF)
        self.assertIn("+    fun sync(): Boolean {", patch)
        self.assertIn("-    fun oldSync() {}", patch)
        self.assertNotIn("+++", patch)

    def test_the_token_resolves_inside_a_code_block(self):
        resolved = context().resolve("{{code_changes}}")
        self.assertIn("fun sync(): Boolean {", resolved)

    def test_no_diff_resolves_to_nothing_rather_than_junk(self):
        self.assertEqual(context(raw_diff="").resolve("{{code_changes}}"), "")

    def test_per_file_line_cap_is_reported_not_silently_dropped(self):
        big = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +1,80 @@\n" + \
              "\n".join(f"+line {n}" for n in range(80))
        code = added_code_from_diff(big, max_lines_per_file=10)

        self.assertIn("line 9", code)
        self.assertNotIn("line 40", code)
        self.assertIn("70 more changed line(s)", code)

    def test_file_cap_is_reported(self):
        many = "\n".join(
            f"diff --git a/f{n}.py b/f{n}.py\n--- a/f{n}.py\n+++ b/f{n}.py\n@@ -0,0 +1 @@\n+x = {n}"
            for n in range(CODE_TOKEN_MAX_FILES + 3)
        )
        code = added_code_from_diff(many)
        self.assertIn("and 3 more changed file(s)", code)

    def test_total_budget_stops_a_giant_diff(self):
        many = "\n".join(
            f"diff --git a/f{n}.py b/f{n}.py\n--- a/f{n}.py\n+++ b/f{n}.py\n@@ -0,0 +1,50 @@\n"
            + "\n".join(f"+row {i}" for i in range(50))
            for n in range(6)
        )
        code = added_code_from_diff(many, max_total_lines=40)
        payload = [line for line in code.splitlines() if line.startswith("row ")]
        self.assertLessEqual(len(payload), 40)


class TestBuilderTellsTheUser(unittest.TestCase):
    """A token nobody can discover is not a feature."""

    def _notes(self, kind: str) -> str:
        from dat.models.template_model import FIELD_NOTE, TemplateBlock
        block = TemplateBlock.create(kind)
        return " ".join(f.placeholder for f in content_fields(block) if f.kind == FIELD_NOTE)

    def test_code_block_mentions_the_code_token(self):
        self.assertIn("{{code_changes}}", self._notes(BLOCK_CODE))

    def test_bullet_list_mentions_expansion(self):
        self.assertIn("{{test_cases}}", self._notes(BLOCK_BULLET_LIST))

    def test_table_mentions_row_expansion_and_index(self):
        notes = self._notes(BLOCK_TABLE)
        self.assertIn("{{test_cases}}", notes)
        self.assertIn("{{index}}", notes)


if __name__ == "__main__":
    unittest.main()
