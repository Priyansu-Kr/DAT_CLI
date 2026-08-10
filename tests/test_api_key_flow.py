import os
import tempfile
import unittest
from unittest import mock

from rich.console import Console

from dat.cli.api_key import ensure_ai_mode_chosen, is_valid_api_key
from dat.services.configuration_service import ConfigurationService
from dat.cli.args import parse_args
from dat.commands.save_api_key import SaveApiKeyCommand
from dat.models.config_model import (
    AI_PROVIDER_GEMINI,
    AI_PROVIDER_GIT_DIFF,
    AI_PROVIDER_UNSET,
    DATConfig,
)
from dat.utils.exit_codes import ExitCode

VALID_KEY = "AIza" + "b" * 35


def fake_container(**config_kwargs):
    """A container stub whose config is a real DATConfig, so the code under
    test exercises the same defaults a fresh install has."""
    container = mock.Mock()
    container.config = DATConfig(**config_kwargs)
    container.ai_service.adapter = mock.Mock(api_key=config_kwargs.get("ai_api_key"))
    container.configuration_service.config_file = "/tmp/config.yaml"
    return container


def quiet_console():
    return Console(quiet=True)


class TestKeyValidation(unittest.TestCase):
    def test_accepts_a_realistic_key(self):
        self.assertTrue(is_valid_api_key(VALID_KEY))

    def test_rejects_junk(self):
        for bad in ("", None, "short", "a" * 80, "has spaces in it" + "a" * 20,
                    "https://aistudio.google.com/app/apikey"):
            self.assertFalse(is_valid_api_key(bad), bad)


class TestKeyIsOptional(unittest.TestCase):
    """The reported problem: the toolkit refused to start without a key."""

    def test_answering_no_records_git_diff_mode_and_does_not_ask_for_a_key(self):
        container = fake_container()
        with mock.patch("dat.cli.api_key.Confirm.ask", return_value=False) as confirm, \
             mock.patch("dat.cli.api_key.prompt_for_api_key") as key_prompt:
            ensure_ai_mode_chosen(container, quiet_console(), interactive=True)

        self.assertTrue(confirm.called)
        self.assertFalse(key_prompt.called, "a 'no' must never be followed by a key prompt")
        self.assertEqual(container.config.ai_provider, AI_PROVIDER_GIT_DIFF)
        self.assertIsNone(container.config.ai_api_key)
        self.assertTrue(container.configuration_service.save_config.called)

    def test_a_previous_no_is_never_asked_again(self):
        container = fake_container(ai_provider=AI_PROVIDER_GIT_DIFF)
        with mock.patch("dat.cli.api_key.Confirm.ask") as confirm:
            ensure_ai_mode_chosen(container, quiet_console(), interactive=True)
        self.assertFalse(confirm.called)

    def test_answering_yes_saves_the_key_and_switches_to_gemini(self):
        container = fake_container()
        with mock.patch("dat.cli.api_key.Confirm.ask", return_value=True), \
             mock.patch("dat.cli.api_key.prompt_for_api_key", return_value=VALID_KEY):
            ensure_ai_mode_chosen(container, quiet_console(), interactive=True)

        self.assertEqual(container.config.ai_api_key, VALID_KEY)
        self.assertEqual(container.config.ai_provider, AI_PROVIDER_GEMINI)
        self.assertEqual(container.ai_service.adapter.api_key, VALID_KEY)
        self.assertTrue(container.configuration_service.save_config.called)

    def test_backing_out_of_the_key_prompt_falls_back_to_git_diff(self):
        container = fake_container()
        with mock.patch("dat.cli.api_key.Confirm.ask", return_value=True), \
             mock.patch("dat.cli.api_key.prompt_for_api_key", return_value=None):
            ensure_ai_mode_chosen(container, quiet_console(), interactive=True)

        self.assertEqual(container.config.ai_provider, AI_PROVIDER_GIT_DIFF)
        self.assertIsNone(container.config.ai_api_key)

    def test_an_existing_key_is_used_without_any_question(self):
        container = fake_container(ai_api_key=VALID_KEY, ai_provider=AI_PROVIDER_GEMINI)
        with mock.patch("dat.cli.api_key.Confirm.ask") as confirm:
            ensure_ai_mode_chosen(container, quiet_console(), interactive=True)
        self.assertFalse(confirm.called)

    def test_a_key_from_an_older_version_is_repaired_to_gemini(self):
        container = fake_container(ai_api_key=VALID_KEY, ai_provider=AI_PROVIDER_UNSET)
        ensure_ai_mode_chosen(container, quiet_console(), interactive=True)
        self.assertEqual(container.config.ai_provider, AI_PROVIDER_GEMINI)

    def test_no_terminal_means_no_prompt_and_no_recorded_choice(self):
        """CI or a detached launch must not hang on a question, nor answer it
        on the user's behalf."""
        container = fake_container()
        with mock.patch("dat.cli.api_key.Confirm.ask") as confirm:
            ensure_ai_mode_chosen(container, quiet_console(), interactive=False)

        self.assertFalse(confirm.called)
        self.assertEqual(container.config.ai_provider, AI_PROVIDER_UNSET)
        self.assertFalse(container.configuration_service.save_config.called)

    def test_ctrl_c_at_the_question_does_not_crash_generation(self):
        container = fake_container()
        with mock.patch("dat.cli.api_key.Confirm.ask", side_effect=KeyboardInterrupt):
            ensure_ai_mode_chosen(container, quiet_console(), interactive=True)
        self.assertFalse(container.configuration_service.save_config.called)


class TestEnvironmentSuppliedKey(unittest.TestCase):
    """$DAT_AI_KEY enables Gemini for the run, but must not be copied to disk."""

    def _service(self, tmpdir):
        service = ConfigurationService()
        service.config_dir = tmpdir
        service.config_file = os.path.join(tmpdir, "config.yaml")
        return service

    def test_env_key_is_loaded_but_flagged_as_the_environment_s(self):
        with mock.patch.dict(os.environ, {"DAT_AI_KEY": VALID_KEY}), \
             tempfile.TemporaryDirectory() as tmpdir:
            config = self._service(tmpdir).load_config()

        self.assertEqual(config.ai_api_key, VALID_KEY)
        self.assertTrue(config.ai_key_from_env)

    def test_env_key_is_never_written_to_the_config_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir)
            service.save_config(DATConfig(ai_api_key=VALID_KEY, ai_key_from_env=True))
            with open(service.config_file) as f:
                written = f.read()

        self.assertNotIn(VALID_KEY, written)

    def test_a_typed_key_is_written_to_the_config_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir)
            service.save_config(DATConfig(ai_api_key=VALID_KEY))
            with open(service.config_file) as f:
                written = f.read()

        self.assertIn(VALID_KEY, written)

    def test_repairing_a_stale_provider_does_not_persist_an_env_key(self):
        container = fake_container(ai_api_key=VALID_KEY, ai_provider=AI_PROVIDER_UNSET)
        container.config.ai_key_from_env = True
        ensure_ai_mode_chosen(container, quiet_console(), interactive=True)

        self.assertEqual(container.config.ai_provider, AI_PROVIDER_GEMINI)
        self.assertFalse(container.configuration_service.save_config.called)


class TestSaveApiKeyCommand(unittest.TestCase):
    def test_args_parse(self):
        args = parse_args(["save-api-key"])
        self.assertEqual(args.command, "save-api-key")
        self.assertIsNone(args.api_key)
        self.assertFalse(args.clear)
        self.assertTrue(parse_args(["save-api-key", "--clear"]).clear)
        self.assertEqual(parse_args(["save-api-key", VALID_KEY]).api_key, VALID_KEY)

    def test_prompted_key_is_saved_and_enables_gemini(self):
        container = fake_container(ai_provider=AI_PROVIDER_GIT_DIFF)
        with mock.patch("dat.commands.save_api_key.prompt_for_api_key", return_value=VALID_KEY):
            code = SaveApiKeyCommand(container).execute({})

        self.assertEqual(code, ExitCode.SUCCESS)
        self.assertEqual(container.config.ai_api_key, VALID_KEY)
        self.assertEqual(container.config.ai_provider, AI_PROVIDER_GEMINI)

    def test_key_given_on_the_command_line_is_validated(self):
        container = fake_container()
        code = SaveApiKeyCommand(container).execute({"api_key": "nope"})

        self.assertEqual(code, ExitCode.VALIDATION_ERROR)
        self.assertIsNone(container.config.ai_api_key)
        self.assertFalse(container.configuration_service.save_config.called)

    def test_valid_key_given_on_the_command_line_skips_the_prompt(self):
        container = fake_container()
        with mock.patch("dat.commands.save_api_key.prompt_for_api_key") as prompt:
            code = SaveApiKeyCommand(container).execute({"api_key": VALID_KEY})

        self.assertEqual(code, ExitCode.SUCCESS)
        self.assertFalse(prompt.called)
        self.assertEqual(container.config.ai_api_key, VALID_KEY)

    def test_clear_removes_the_key_and_returns_to_git_diff(self):
        container = fake_container(ai_api_key=VALID_KEY, ai_provider=AI_PROVIDER_GEMINI)
        code = SaveApiKeyCommand(container).execute({"clear": True})

        self.assertEqual(code, ExitCode.SUCCESS)
        self.assertIsNone(container.config.ai_api_key)
        self.assertEqual(container.config.ai_provider, AI_PROVIDER_GIT_DIFF)

    def test_cancelling_the_prompt_saves_nothing(self):
        container = fake_container()
        with mock.patch("dat.commands.save_api_key.prompt_for_api_key", return_value=None):
            code = SaveApiKeyCommand(container).execute({})

        self.assertEqual(code, ExitCode.SUCCESS)
        self.assertFalse(container.configuration_service.save_config.called)


if __name__ == "__main__":
    unittest.main()
