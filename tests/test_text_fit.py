import unittest

from dat.gui.text_fit import ELLIPSIS, truncate_to_length, truncate_to_width


def fixed_width(char_px: int = 10):
    """Stand-in for Tk's font.measure(): every character is char_px wide."""
    return lambda text: len(text) * char_px


class TestTruncateToWidth(unittest.TestCase):
    def test_text_that_fits_is_untouched(self):
        self.assertEqual(truncate_to_width("Short", fixed_width(), 500), "Short")

    def test_exactly_filling_the_space_is_untouched(self):
        self.assertEqual(truncate_to_width("abcde", fixed_width(), 50), "abcde")

    def test_long_text_is_cut_and_marked(self):
        result = truncate_to_width("A very long document title", fixed_width(), 100)
        self.assertTrue(result.endswith(ELLIPSIS), result)
        self.assertEqual(len(result) * 10, 100)
        self.assertTrue("A very long document title".startswith(result[:-1].rstrip()))

    def test_result_never_exceeds_the_budget(self):
        measure = fixed_width(7)
        text = "Ticket-1234 A rather long feature topic that will not fit"
        for width in range(0, 400, 13):
            result = truncate_to_width(text, measure, width)
            if result and width > 0:
                self.assertLessEqual(measure(result), max(width, measure(ELLIPSIS)), (width, result))

    def test_trailing_space_before_the_ellipsis_is_trimmed(self):
        result = truncate_to_width("alpha beta gamma", fixed_width(), 70)
        self.assertNotIn(" " + ELLIPSIS, result)

    def test_no_room_at_all_returns_nothing(self):
        self.assertEqual(truncate_to_width("anything", fixed_width(), 5), "")

    def test_non_positive_width_is_treated_as_unknown(self):
        # Before the first layout pass Tk reports width 0/1; showing the full
        # string then is better than blanking the header.
        self.assertEqual(truncate_to_width("Title", fixed_width(), 0), "Title")
        self.assertEqual(truncate_to_width("Title", fixed_width(), -20), "Title")

    def test_empty_text(self):
        self.assertEqual(truncate_to_width("", fixed_width(), 100), "")

    def test_variable_width_measurement(self):
        """Works with a real proportional font, not just fixed-width."""
        widths = {"i": 3, "W": 14, ELLIPSIS: 8}
        measure = lambda t: sum(widths.get(ch, 7) for ch in t)

        self.assertEqual(truncate_to_width("iii", measure, 20), "iii")
        result = truncate_to_width("WWWWWW", measure, 40)
        self.assertTrue(result.endswith(ELLIPSIS))
        self.assertLessEqual(measure(result), 40)


class TestTruncateToLength(unittest.TestCase):
    def test_short_text_is_untouched(self):
        self.assertEqual(truncate_to_length("Overview", 20), "Overview")

    def test_long_text_is_capped_including_the_ellipsis(self):
        result = truncate_to_length("A very long section title", 10)
        self.assertEqual(len(result), 10)
        self.assertTrue(result.endswith(ELLIPSIS))

    def test_whitespace_is_trimmed(self):
        self.assertEqual(truncate_to_length("  padded  ", 20), "padded")
        self.assertNotIn(" " + ELLIPSIS, truncate_to_length("alpha beta gamma", 8))

    def test_degenerate_limits(self):
        self.assertEqual(truncate_to_length("anything", 0), "")
        self.assertEqual(truncate_to_length("anything", 1), ELLIPSIS)

    def test_handles_none(self):
        self.assertEqual(truncate_to_length(None, 10), "")


if __name__ == "__main__":
    unittest.main()
