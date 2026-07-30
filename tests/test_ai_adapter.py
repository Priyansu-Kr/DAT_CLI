import unittest
from dat.adapters.ai_adapter import AIAdapter

class TestAIAdapter(unittest.TestCase):
    def test_rule_based_summary_with_kotlin_files(self):
        adapter = AIAdapter(provider="rule-based")
        summary = adapter.generate_summary(
            title="Login Screen",
            changed_files=["app/src/LoginActivity.kt", "app/res/layout/activity_login.xml"],
            commits=["Added login form validation"],
            raw_diff="+ fun validateEmail() {}"
        )
        self.assertIn("Login Screen", summary.overview)
        self.assertTrue(len(summary.key_points) > 0)
        self.assertTrue(len(summary.impact_areas) > 0)
        self.assertTrue(len(summary.test_recommendations) > 0)

    def test_rule_based_summary_with_python_files(self):
        adapter = AIAdapter(provider="rule-based")
        summary = adapter.generate_summary(
            title="API Refactor",
            changed_files=["services/auth.py", "services/user.py"],
            commits=["Refactored auth service"],
            raw_diff=""
        )
        self.assertIn("API Refactor", summary.overview)
        self.assertTrue(any("Python" in pt for pt in summary.key_points))

    def test_rule_based_summary_empty_files(self):
        adapter = AIAdapter(provider="rule-based")
        summary = adapter.generate_summary(
            title="Empty Feature",
            changed_files=[],
            commits=[],
            raw_diff=""
        )
        self.assertIn("Empty Feature", summary.overview)
        self.assertTrue(len(summary.key_points) > 0)

if __name__ == "__main__":
    unittest.main()
