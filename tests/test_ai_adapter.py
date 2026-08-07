import json
import unittest
from unittest import mock

from dat.adapters.ai_adapter import (
    GEMINI_CONNECT_TIMEOUT,
    GEMINI_READ_TIMEOUT,
    AIAdapter,
)


def gemini_response(payload=None):
    """A minimal successful generateContent response."""
    payload = payload or {
        "overview": "Did the thing.",
        "key_points": ["Changed A", "Changed B"],
        "impact_areas": ["Module"],
        "test_cases": ["Verify A", "Verify B"],
        "test_recommendations": ["Run the app"],
    }
    response = mock.Mock()
    response.raise_for_status = mock.Mock()
    response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]
    }
    return response


def big_diff(files=12, lines=200):
    sections = []
    for index in range(files):
        body = "\n".join(f"+line {n} of file {index} " + "y" * 40 for n in range(lines))
        sections.append(
            f"diff --git a/src/mod_{index}.py b/src/mod_{index}.py\n"
            f"--- a/src/mod_{index}.py\n+++ b/src/mod_{index}.py\n@@ -1,0 +1,{lines} @@\n{body}"
        )
    return "\n".join(sections)


class TestGeminiRequest(unittest.TestCase):
    def setUp(self):
        self.adapter = AIAdapter(provider="gemini", api_key="k" * 40)

    def _call(self, **kwargs):
        defaults = dict(title="T", changed_files=["a.py"], commits=["c"], raw_diff="+x")
        defaults.update(kwargs)
        with mock.patch("dat.adapters.ai_adapter.requests.post",
                        return_value=gemini_response()) as post:
            summary = self.adapter.generate_summary(**defaults)
        return summary, post.call_args

    def test_request_has_a_timeout(self):
        """Without one, a hung connection blocks the CLI indefinitely."""
        _summary, call = self._call()
        self.assertEqual(call.kwargs["timeout"], (GEMINI_CONNECT_TIMEOUT, GEMINI_READ_TIMEOUT))

    def test_api_key_travels_in_a_header_not_the_url(self):
        _summary, call = self._call()
        url = call.args[0]

        self.assertNotIn("key=", url)
        self.assertNotIn("k" * 40, url)
        self.assertEqual(call.kwargs["headers"]["x-goog-api-key"], "k" * 40)

    def test_asks_for_json_directly(self):
        _summary, call = self._call()
        config = call.kwargs["json"]["generationConfig"]
        self.assertEqual(config["response_mime_type"], "application/json")
        self.assertIn("maxOutputTokens", config)

    def test_markdown_fenced_json_is_still_parsed(self):
        fenced = mock.Mock()
        fenced.raise_for_status = mock.Mock()
        fenced.json.return_value = {"candidates": [{"content": {"parts": [
            {"text": '```json\n{"overview": "ok", "test_cases": ["t"]}\n```'}
        ]}}]}
        with mock.patch("dat.adapters.ai_adapter.requests.post", return_value=fenced):
            summary = self.adapter.generate_summary(
                title="T", changed_files=[], commits=[], raw_diff="")
        self.assertEqual(summary.overview, "ok")

    def test_network_failure_falls_back_to_rule_based(self):
        with mock.patch("dat.adapters.ai_adapter.requests.post",
                        side_effect=OSError("connection reset")):
            summary = self.adapter.generate_summary(
                title="Login", changed_files=["a.kt"], commits=[], raw_diff="")
        self.assertIn("Login", summary.overview)
        self.assertTrue(summary.test_cases)


class TestPromptContents(unittest.TestCase):
    def setUp(self):
        self.adapter = AIAdapter(provider="gemini", api_key="k" * 40)

    def prompt_for(self, **kwargs):
        defaults = dict(title="T", changed_files=["a.py"], commits=["c"], raw_diff="+x")
        defaults.update(kwargs)
        return self.adapter._build_prompt(**defaults)

    def test_large_diff_covers_every_file_not_just_the_first(self):
        diff = big_diff(files=12)
        prompt = self.prompt_for(raw_diff=diff, changed_files=[f"src/mod_{i}.py" for i in range(12)])

        for index in range(12):
            self.assertIn(f"src/mod_{index}.py", prompt, f"mod_{index} missing from the prompt")

    def test_prompt_declares_what_was_omitted(self):
        prompt = self.prompt_for(raw_diff=big_diff(files=40, lines=300))
        self.assertIn("Diff coverage:", prompt)
        self.assertIn("do not claim they were unaffected", prompt)

    def test_prompt_reports_a_complete_diff_as_complete(self):
        prompt = self.prompt_for(raw_diff=big_diff(files=1, lines=3))
        self.assertIn("Complete diff", prompt)

    def test_requested_counts_scale_with_the_change_size(self):
        small = self.prompt_for(changed_files=["a.py"], raw_diff=big_diff(files=1, lines=5))
        large = self.prompt_for(
            changed_files=[f"f{i}.py" for i in range(20)], raw_diff=big_diff(files=20, lines=5)
        )
        self.assertIn("3-4", small)   # test cases for a tiny change
        self.assertIn("5-8", large)   # more for a twenty-file feature

    def test_file_list_and_commits_are_included_in_full(self):
        prompt = self.prompt_for(
            changed_files=["one.py", "two.py"], commits=["first commit", "second commit"]
        )
        self.assertIn("one.py", prompt)
        self.assertIn("two.py", prompt)
        self.assertIn("first commit", prompt)
        self.assertIn("second commit", prompt)

    def test_handles_no_files_or_commits(self):
        prompt = self.prompt_for(changed_files=[], commits=[], raw_diff="")
        self.assertIn("unknown", prompt)
        self.assertIn("none", prompt)


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
