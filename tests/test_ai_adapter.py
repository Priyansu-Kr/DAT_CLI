import json
import os
import unittest
from unittest import mock

from dat.adapters.ai_adapter import (
    AI_DEADLINE_BASE_SECONDS,
    AI_DEADLINE_ENV_VAR,
    AI_DEADLINE_MAX_SECONDS,
    GEMINI_CONNECT_TIMEOUT,
    GEMINI_MAX_OUTPUT_TOKENS,
    AIAdapter,
    deadline_for_diff,
    resolve_ai_deadline,
)
from dat.models.config_model import AI_PROVIDER_GIT_DIFF


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
        connect, read = call.kwargs["timeout"]
        self.assertEqual(connect, GEMINI_CONNECT_TIMEOUT)
        # The read half is the answer deadline, so a small change gets the
        # base wait rather than a minute-plus stall.
        self.assertEqual(read, AI_DEADLINE_BASE_SECONDS)

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

    def test_network_failure_falls_back_to_the_git_diff(self):
        with mock.patch("dat.adapters.ai_adapter.requests.post",
                        side_effect=OSError("connection reset")):
            summary = self.adapter.generate_summary(
                title="Login", changed_files=["app/src/a.kt"], commits=[], raw_diff="")
        self.assertIn("Login", summary.overview)
        self.assertEqual(summary.key_points, ["a.kt"])
        self.assertEqual(summary.test_cases, [])


class TestAnswerDeadline(unittest.TestCase):
    """A user watching the Preview Panel won't wait out a long stall, but a
    big change still needs long enough to be summarised at all."""

    def test_small_change_gets_the_short_base_deadline(self):
        self.assertEqual(resolve_ai_deadline(12_000), AI_DEADLINE_BASE_SECONDS)

    def test_deadline_grows_with_the_prompt(self):
        small = resolve_ai_deadline(50_000)
        large = resolve_ai_deadline(300_000)
        self.assertGreater(large, small)

    def test_deadline_is_capped(self):
        self.assertEqual(resolve_ai_deadline(50_000_000), AI_DEADLINE_MAX_SECONDS)

    def test_env_var_pins_the_deadline(self):
        with mock.patch.dict(os.environ, {AI_DEADLINE_ENV_VAR: "7.5"}):
            self.assertEqual(resolve_ai_deadline(12_000), 7.5)
            self.assertEqual(resolve_ai_deadline(5_000_000), 7.5)

    def test_junk_env_var_is_ignored(self):
        for bad in ("abc", "0", "-5", ""):
            with mock.patch.dict(os.environ, {AI_DEADLINE_ENV_VAR: bad}):
                self.assertEqual(resolve_ai_deadline(1_000), AI_DEADLINE_BASE_SECONDS)

    def test_diff_estimate_never_exceeds_the_packed_budget(self):
        """The GUI predicts the deadline from the raw diff, which can be far
        larger than what actually gets sent."""
        huge = "x" * 5_000_000
        self.assertEqual(deadline_for_diff(huge), resolve_ai_deadline(200_000))

    def test_a_bigger_response_is_requested_than_a_single_screen(self):
        self.assertGreaterEqual(GEMINI_MAX_OUTPUT_TOKENS, 4096)


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


class TestGitDiffPillar(unittest.TestCase):
    """With no API key, the changed files ARE the content and nothing is
    invented - the user writes the test cases themselves."""

    def _summary(self, **kwargs):
        defaults = dict(title="Login Screen", changed_files=[], commits=[], raw_diff="")
        defaults.update(kwargs)
        return AIAdapter(provider=AI_PROVIDER_GIT_DIFF, api_key=None).generate_summary(**defaults)

    def test_no_api_key_never_calls_gemini(self):
        with mock.patch("dat.adapters.ai_adapter.requests.post") as post:
            self._summary(changed_files=["a.py"])
        self.assertFalse(post.called)

    def test_changed_files_become_the_key_points(self):
        summary = self._summary(changed_files=[
            "app/src/main/java/com/x/service.kt",
            "app/src/main/res/layout/activity_main.xml",
        ])
        self.assertEqual(summary.key_points, ["service.kt", "activity_main.xml"])

    def test_test_cases_are_left_empty_for_the_user(self):
        summary = self._summary(changed_files=["service.kt"])
        self.assertEqual(summary.test_cases, [])
        self.assertEqual(summary.test_recommendations, [])

    def test_overview_names_the_feature_and_counts_the_files(self):
        summary = self._summary(title="API Refactor", changed_files=["auth.py", "user.py"])
        self.assertIn("API Refactor", summary.overview)
        self.assertIn("2 files", summary.overview)

    def test_single_file_reads_as_singular(self):
        self.assertIn("1 file.", self._summary(changed_files=["auth.py"]).overview)

    def test_same_named_files_in_different_modules_stay_distinguishable(self):
        summary = self._summary(changed_files=[
            "collector/src/Repository.kt",
            "admin/src/Repository.kt",
            "admin/src/Main.kt",
        ])
        # Grows leftwards only as far as it must: 'src/Repository.kt' would
        # still be ambiguous, while Main.kt stays a bare name.
        self.assertEqual(
            summary.key_points,
            ["collector/src/Repository.kt", "admin/src/Repository.kt", "Main.kt"],
        )

    def test_no_changed_files_says_so_rather_than_inventing_content(self):
        summary = self._summary(title="Empty Feature")
        self.assertIn("Empty Feature", summary.overview)
        self.assertIn("No changed files", summary.overview)
        self.assertEqual(summary.key_points, [])


class TestSavedKeyAlwaysUsesGemini(unittest.TestCase):
    def test_stale_provider_does_not_strand_a_configured_user(self):
        """A key saved by an older DAT (provider still 'rule-based') must
        still reach Gemini."""
        adapter = AIAdapter(provider="rule-based", api_key="k" * 40)
        with mock.patch("dat.adapters.ai_adapter.requests.post",
                        return_value=gemini_response()) as post:
            summary = adapter.generate_summary(
                title="T", changed_files=["a.py"], commits=[], raw_diff="+x")

        self.assertTrue(post.called)
        self.assertEqual(summary.overview, "Did the thing.")

if __name__ == "__main__":
    unittest.main()
