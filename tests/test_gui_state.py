import unittest

from dat.gui.state import GuiState, build_preview_content
from dat.models.doc_request import ChangeSummary
from dat.models.git_info import GitInfo
from dat.models.screenshot_info import ScreenshotInfo


class TestGuiState(unittest.TestCase):
    def test_from_git_info_prefills_and_strips_ticket_prefix(self):
        git_info = GitInfo(
            branch_name="feature/NSWM-6374-add-bin-ward-toggle",
            inferred_title="NSWM-6374 Add Bin Ward Toggle",
            ticket_id="NSWM-6374",
            author_name="Priyansu Kumar",
        )
        state = GuiState.from_git_info(git_info)
        self.assertEqual(state.ticket_id, "NSWM-6374")
        self.assertEqual(state.topic, "Add Bin Ward Toggle")
        self.assertEqual(state.author, "Priyansu Kumar")

    def test_title_combines_ticket_and_topic(self):
        state = GuiState(ticket_id="JIRA-1", topic="Login Flow")
        self.assertEqual(state.title, "JIRA-1 Login Flow")

    def test_title_falls_back_when_empty(self):
        state = GuiState(ticket_id="", topic="")
        self.assertEqual(state.title, "Untitled Feature")

    def test_add_and_remove_screenshot(self):
        state = GuiState()
        state.add_screenshot(ScreenshotInfo(file_path="/tmp/a.png"))
        state.add_screenshot(ScreenshotInfo(file_path="/tmp/b.png"))
        self.assertEqual(len(state.screenshots), 2)
        state.remove_screenshot("/tmp/a.png")
        self.assertEqual([s.file_path for s in state.screenshots], ["/tmp/b.png"])

    def test_build_preview_content_all_toggles_on(self):
        state = GuiState(
            ticket_id="PAY-500",
            topic="Payment Gateway Integration",
            author="Lead Dev",
            summary=ChangeSummary(
                overview="Implemented a new payment gateway.",
                key_points=["Added Stripe adapter", "Wired webhook handler"],
                impact_areas=["Checkout"],
                test_cases=["Verify checkout completes", "Verify webhook retried on failure"],
            ),
            screenshots=[ScreenshotInfo(file_path="/tmp/shot.png")],
        )
        blocks = build_preview_content(state)
        kinds = [b.kind for b in blocks]
        self.assertEqual(
            kinds,
            ["title", "metadata_table", "changes_done", "test_cases_table", "screenshots"],
        )
        self.assertEqual(blocks[0].text, "PAY-500 Payment Gateway Integration")
        self.assertEqual(blocks[3].table_rows[0], ["1.", "Verify checkout completes", "Success"])

    def test_build_preview_content_respects_toggles_off(self):
        state = GuiState(ticket_id="X-1", topic="Topic")
        state.set_toggle("metadata_table", False)
        state.set_toggle("test_cases_table", False)
        blocks = build_preview_content(state)
        kinds = [b.kind for b in blocks]
        self.assertNotIn("metadata_table", kinds)
        self.assertNotIn("test_cases_table", kinds)
        self.assertIn("title", kinds)

    def test_build_preview_content_no_summary_falls_back(self):
        state = GuiState(ticket_id="X-1", topic="Topic")
        blocks = build_preview_content(state)
        changes_block = next(b for b in blocks if b.kind == "changes_done")
        self.assertEqual(changes_block.bullets, ["Implemented core logic changes."])
        self.assertIn("Main Module", changes_block.text)

    def test_editable_summary_setters_mark_user_edited(self):
        state = GuiState()
        self.assertFalse(state.summary_user_edited)

        state.set_key_points(["Manually written point."])
        self.assertTrue(state.summary_user_edited)
        self.assertEqual(state.summary.key_points, ["Manually written point."])

    def test_set_approved_by(self):
        state = GuiState()
        state.set_approved_by("Reviewer Name")
        self.assertEqual(state.approved_by, "Reviewer Name")

    def test_set_impact_areas_text_parses_csv(self):
        state = GuiState()
        state.set_impact_areas_text("Checkout,  Payments ,Cart")
        self.assertEqual(state.summary.impact_areas, ["Checkout", "Payments", "Cart"])

    def test_set_key_points_drops_blank_lines(self):
        state = GuiState()
        state.set_key_points(["Added retry logic", "", "  ", "Fixed timeout"])
        self.assertEqual(state.summary.key_points, ["Added retry logic", "Fixed timeout"])

    def test_set_test_cases_clears_out_of_range_screenshot_assignment(self):
        state = GuiState()
        state.summary.test_cases = ["Case A", "Case B", "Case C"]
        state.add_screenshot(ScreenshotInfo(file_path="/tmp/a.png", test_case_index=2))

        state.set_test_cases(["Case A", "Case B"])

        self.assertEqual(state.summary.test_cases, ["Case A", "Case B"])
        self.assertIsNone(state.screenshots[0].test_case_index)

    def test_screenshot_assignment_and_reorder(self):
        state = GuiState()
        state.summary.test_cases = ["Case A", "Case B"]
        state.add_screenshot(ScreenshotInfo(file_path="/tmp/a.png"))
        state.add_screenshot(ScreenshotInfo(file_path="/tmp/b.png"))

        state.set_screenshot_test_case("/tmp/b.png", 0)
        self.assertEqual(state.screenshots[1].test_case_index, 0)

        state.reorder_screenshots(["/tmp/b.png", "/tmp/a.png"])
        self.assertEqual([s.file_path for s in state.screenshots], ["/tmp/b.png", "/tmp/a.png"])

    def test_build_preview_content_screenshots_grouped_by_test_case(self):
        state = GuiState(ticket_id="X-1", topic="Topic")
        state.summary.test_cases = ["Case A", "Case B"]
        state.add_screenshot(ScreenshotInfo(file_path="/tmp/a.png", test_case_index=1))
        state.add_screenshot(ScreenshotInfo(file_path="/tmp/b.png", test_case_index=0))

        blocks = build_preview_content(state)
        shots_block = next(b for b in blocks if b.kind == "screenshots")
        labels = [label for _, label, _ in shots_block.screenshot_groups]
        self.assertEqual(labels, ["Test Case 1 : Case A", "Test Case 2 : Case B"])
        case_a_shots = shots_block.screenshot_groups[0][2]
        self.assertEqual([s.file_path for s in case_a_shots], ["/tmp/b.png"])


if __name__ == "__main__":
    unittest.main()
