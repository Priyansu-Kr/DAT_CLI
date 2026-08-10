import unittest
from unittest import mock

from dat.utils.diff_budget import (
    DEFAULT_DIFF_CHAR_BUDGET,
    DIFF_CHAR_BUDGET_ENV_VAR,
    MIN_CHARS_PER_FILE,
    pack_diff,
    resolve_char_budget,
    split_diff_by_file,
)


def file_section(path: str, body_lines: int, marker: str = "x") -> str:
    body = "\n".join(f"+{marker * 40}" for _ in range(body_lines))
    return (
        f"diff --git a/{path} b/{path}\n"
        f"index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -1,0 +1,{body_lines} @@\n"
        f"{body}"
    )


def multi_file_diff(count: int, body_lines: int = 60) -> str:
    return "\n".join(file_section(f"src/file_{i}.py", body_lines, marker=chr(97 + i % 26))
                     for i in range(count))


class TestSplitDiffByFile(unittest.TestCase):
    def test_splits_on_file_headers(self):
        sections = split_diff_by_file(multi_file_diff(3))
        self.assertEqual([path for path, _ in sections],
                         ["src/file_0.py", "src/file_1.py", "src/file_2.py"])

    def test_empty_diff(self):
        self.assertEqual(split_diff_by_file(""), [])
        self.assertEqual(split_diff_by_file("   \n  "), [])

    def test_content_before_any_header_is_kept(self):
        sections = split_diff_by_file("warning: something\n" + file_section("a.py", 2))
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0][0], "(unknown)")

    def test_paths_with_spaces(self):
        sections = split_diff_by_file(file_section("src/my file.py", 2))
        self.assertEqual(sections[0][0], "src/my file.py")


class TestPackDiff(unittest.TestCase):
    def test_small_diff_is_returned_untouched(self):
        diff = multi_file_diff(2, body_lines=3)
        packed, stats = pack_diff(diff, budget_chars=100_000)

        self.assertEqual(packed, diff)
        self.assertTrue(stats.is_complete)
        self.assertEqual(stats.included_files, 2)
        self.assertEqual(stats.omitted_file_count, 0)

    def test_every_file_gets_a_share_instead_of_the_first_one_taking_all(self):
        """The reported bug: diff[:N] summarised a 13-file change from 1 file."""
        diff = multi_file_diff(10, body_lines=100)
        packed, stats = pack_diff(diff, budget_chars=20_000)

        for index in range(10):
            self.assertIn(f"src/file_{index}.py", packed, f"file_{index} missing")
        self.assertEqual(stats.included_files, 10)
        self.assertLessEqual(len(packed), 21_000)

        # For contrast, a flat slice of the same budget reaches only the
        # first few files and never mentions the rest.
        flat_slice_files = len(split_diff_by_file(diff[:20_000]))
        self.assertLess(flat_slice_files, 10)
        self.assertGreater(stats.included_files, flat_slice_files)

    def test_respects_the_budget(self):
        diff = multi_file_diff(6, body_lines=200)
        for budget in (2_000, 5_000, 30_000):
            packed, _stats = pack_diff(diff, budget_chars=budget)
            self.assertLessEqual(len(packed), budget * 1.1, budget)

    def test_file_headers_survive_trimming(self):
        diff = multi_file_diff(4, body_lines=300)
        packed, _stats = pack_diff(diff, budget_chars=4_000)

        for index in range(4):
            path = f"src/file_{index}.py"
            self.assertIn(f"diff --git a/{path} b/{path}", packed)
            self.assertIn(f"+++ b/{path}", packed)

    def test_trimmed_files_are_marked_in_the_text_and_the_stats(self):
        diff = multi_file_diff(3, body_lines=200)
        packed, stats = pack_diff(diff, budget_chars=3_000)

        self.assertIn("more diff line(s) in this file omitted", packed)
        self.assertTrue(stats.truncated_files)
        self.assertFalse(stats.is_complete)

    def test_files_that_cannot_get_a_useful_share_are_reported_as_omitted(self):
        diff = multi_file_diff(40, body_lines=50)
        budget = 4_000
        _packed, stats = pack_diff(diff, budget_chars=budget)

        self.assertEqual(stats.included_files, budget // MIN_CHARS_PER_FILE)
        self.assertEqual(stats.omitted_file_count, 40 - stats.included_files)
        self.assertEqual(stats.total_files, 40)

    def test_describe_names_what_was_left_out(self):
        _packed, stats = pack_diff(multi_file_diff(20, body_lines=80), budget_chars=3_000)
        description = stats.describe()

        self.assertIn("of 20 file(s) included", description)
        self.assertIn("Not shown at all", description)
        self.assertIn("do not claim they were unaffected", description)

    def test_describe_on_a_complete_diff(self):
        _packed, stats = pack_diff(multi_file_diff(2, body_lines=2), budget_chars=100_000)
        self.assertIn("Complete diff", stats.describe())

    def test_describe_with_no_diff(self):
        packed, stats = pack_diff("", budget_chars=1_000)
        self.assertEqual(packed, "")
        self.assertIn("No code diff", stats.describe())

    def test_single_huge_file_is_trimmed_not_dropped(self):
        diff = file_section("src/giant.py", 5_000)
        packed, stats = pack_diff(diff, budget_chars=2_000)

        self.assertIn("src/giant.py", packed)
        self.assertEqual(stats.included_files, 1)
        self.assertEqual(stats.omitted_file_count, 0)

    def test_unused_share_from_a_small_file_helps_later_files(self):
        diff = file_section("small.py", 1) + "\n" + file_section("big.py", 400)
        packed, _stats = pack_diff(diff, budget_chars=8_000)

        # The big file should get well beyond an even half of the budget.
        big_section = packed.split("diff --git a/big.py")[1]
        self.assertGreater(len(big_section), 4_500)


class TestResolveCharBudget(unittest.TestCase):
    def test_explicit_wins(self):
        self.assertEqual(resolve_char_budget(1234), 1234)

    def test_environment_override(self):
        with mock.patch.dict("os.environ", {DIFF_CHAR_BUDGET_ENV_VAR: "5000"}):
            self.assertEqual(resolve_char_budget(), 5000)

    def test_default_when_unset(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(resolve_char_budget(), DEFAULT_DIFF_CHAR_BUDGET)

    def test_invalid_environment_values_fall_back(self):
        for bogus in ("abc", "0", "-100", ""):
            with mock.patch.dict("os.environ", {DIFF_CHAR_BUDGET_ENV_VAR: bogus}):
                self.assertEqual(resolve_char_budget(), DEFAULT_DIFF_CHAR_BUDGET, bogus)

    def test_non_positive_explicit_falls_back(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(resolve_char_budget(0), DEFAULT_DIFF_CHAR_BUDGET)


if __name__ == "__main__":
    unittest.main()
