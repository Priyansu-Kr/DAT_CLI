import unittest

from dat.models.screenshot_info import ScreenshotInfo
from dat.renderers.screenshot_grouping import group_screenshots_by_test_case


class TestScreenshotGrouping(unittest.TestCase):
    def test_no_test_cases_returns_single_bucket(self):
        shots = [ScreenshotInfo(file_path="/tmp/a.png")]
        groups = group_screenshots_by_test_case(shots, [])
        self.assertEqual(len(groups), 1)
        case_idx, label, group_shots = groups[0]
        self.assertIsNone(case_idx)
        self.assertEqual(label, "Screenshots")
        self.assertEqual(group_shots, shots)

    def test_no_screenshots_returns_empty(self):
        self.assertEqual(group_screenshots_by_test_case([], ["Case A"]), [])

    def test_auto_distributes_when_no_assignment(self):
        shots = [ScreenshotInfo(file_path=f"/tmp/{i}.png") for i in range(3)]
        groups = group_screenshots_by_test_case(shots, ["Case A", "Case B"])
        self.assertEqual(len(groups), 2)
        # 3 shots over 2 cases -> remainder goes to the first case (2 then 1)
        self.assertEqual(len(groups[0][2]), 2)
        self.assertEqual(len(groups[1][2]), 1)
        self.assertEqual(groups[0][1], "Test Case 1 : Case A")

    def test_explicit_assignment_overrides_auto_distribution(self):
        shots = [
            ScreenshotInfo(file_path="/tmp/a.png", test_case_index=1),
            ScreenshotInfo(file_path="/tmp/b.png", test_case_index=1),
            ScreenshotInfo(file_path="/tmp/c.png", test_case_index=0),
        ]
        groups = group_screenshots_by_test_case(shots, ["Case A", "Case B"])
        self.assertEqual(len(groups), 2)
        case_a_shots = groups[0][2]
        case_b_shots = groups[1][2]
        self.assertEqual([s.file_path for s in case_a_shots], ["/tmp/c.png"])
        self.assertEqual([s.file_path for s in case_b_shots], ["/tmp/a.png", "/tmp/b.png"])

    def test_unassigned_and_out_of_range_go_to_additional_bucket(self):
        shots = [
            ScreenshotInfo(file_path="/tmp/a.png", test_case_index=0),
            ScreenshotInfo(file_path="/tmp/b.png", test_case_index=None),
            ScreenshotInfo(file_path="/tmp/c.png", test_case_index=5),
        ]
        groups = group_screenshots_by_test_case(shots, ["Case A"])
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0][1], "Test Case 1 : Case A")
        self.assertEqual([s.file_path for s in groups[0][2]], ["/tmp/a.png"])
        self.assertEqual(groups[1][1], "Additional Screenshots")
        self.assertEqual([s.file_path for s in groups[1][2]], ["/tmp/b.png", "/tmp/c.png"])


if __name__ == "__main__":
    unittest.main()
