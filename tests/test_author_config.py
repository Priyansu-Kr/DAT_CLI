"""Who a generated document says it was created by.

The rule under test throughout: a name the user chose wins, and only when
there is none does DAT fall back to the git author, then to a placeholder.
"""
import os
import tempfile
from unittest import mock

import docx
import pytest
import yaml

from dat.cli.args import parse_args
from dat.commands.config_cmd import ConfigCommand, find_setting
from dat.models.config_model import (
    DATConfig,
    PLACEHOLDER_AUTHOR_EMAIL,
    PLACEHOLDER_AUTHOR_NAME,
)
from dat.models.git_info import GitInfo
from dat.services.configuration_service import ConfigurationService
from dat.services.document_service import DocumentService
from dat.utils.exit_codes import ExitCode


@pytest.fixture
def config_service(tmp_path, monkeypatch):
    service = ConfigurationService()
    monkeypatch.setattr(service, "config_dir", str(tmp_path))
    monkeypatch.setattr(service, "config_file", str(tmp_path / "config.yaml"))
    monkeypatch.delenv("DAT_AUTHOR", raising=False)
    monkeypatch.delenv("DAT_AI_KEY", raising=False)
    return service


def _write(service, payload):
    with open(service.config_file, "w", encoding="utf-8") as f:
        yaml.dump(payload, f)


class TestLoadingTheAuthor:
    def test_a_real_name_counts_as_chosen(self, config_service):
        _write(config_service, {"author_name": "Priyansu Tandel"})
        config = config_service.load_config()

        assert config.author_name_set
        assert config.configured_author_name == "Priyansu Tandel"

    def test_a_legacy_placeholder_does_not_count_as_chosen(self, config_service):
        # Every config written by an older DAT contains this line, because
        # `config init` saved the dataclass defaults. Treating it as a choice
        # would put "Developer" on those users' documents forever.
        _write(config_service, {"author_name": PLACEHOLDER_AUTHOR_NAME})
        config = config_service.load_config()

        assert not config.author_name_set
        assert config.configured_author_name is None

    def test_a_blank_name_does_not_count_as_chosen(self, config_service):
        _write(config_service, {"author_name": "   "})
        assert config_service.load_config().configured_author_name is None

    def test_missing_file_leaves_the_author_unset(self, config_service):
        assert config_service.load_config().configured_author_name is None

    def test_env_author_counts_as_chosen(self, config_service, monkeypatch):
        monkeypatch.setenv("DAT_AUTHOR", "CI Robot")
        config = config_service.load_config()

        assert config.author_name_set
        assert config.configured_author_name == "CI Robot"

    def test_placeholder_email_does_not_count_as_chosen(self, config_service):
        _write(config_service, {"author_email": PLACEHOLDER_AUTHOR_EMAIL})
        assert config_service.load_config().configured_author_email is None


class TestSavingTheAuthor:
    def test_a_chosen_name_is_written(self, config_service):
        config = DATConfig(author_name="Priyansu Tandel", author_name_set=True)
        config_service.save_config(config)

        with open(config_service.config_file, encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        assert saved["author_name"] == "Priyansu Tandel"

    def test_an_unset_name_is_not_written(self, config_service):
        config_service.save_config(DATConfig())

        with open(config_service.config_file, encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        # Absence is what keeps "unset" distinguishable from "chose the
        # placeholder" on the next load.
        assert "author_name" not in saved
        assert "author_email" not in saved

    def test_a_saved_name_survives_a_round_trip(self, config_service):
        config = config_service.load_config()
        config.author_name = "Priyansu Tandel"
        config.author_name_set = True
        config_service.save_config(config)

        assert config_service.load_config().configured_author_name == "Priyansu Tandel"


class TestDocumentAuthorResolution:
    """DocumentService is where the final 'Created By' value is decided."""

    def _service(self, git_author):
        git_service = mock.Mock()
        git_service.get_git_info.return_value = GitInfo(
            branch_name="fix-bugs",
            inferred_title="Bugs",
            ticket_id=None,
            author_name=git_author,
        )
        ai_service = mock.Mock()
        ai_service.generate_change_summary.return_value = None
        return DocumentService(git_service=git_service, ai_service=ai_service)

    def _created_by(self, service, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "doc.docx")
            service.generate_documentation(output_path=out, **kwargs)
            table = docx.Document(out).tables[0]
            rows = {r.cells[0].text.strip(): r.cells[1].text.strip() for r in table.rows}
            return rows["Created By"]

    def test_a_configured_name_wins_over_the_git_author(self):
        service = self._service(git_author="Branch Name Author")
        assert self._created_by(service, author="Priyansu Tandel") == "Priyansu Tandel"

    def test_the_git_author_is_used_when_no_name_is_configured(self):
        service = self._service(git_author="Branch Name Author")
        assert self._created_by(service, author=None) == "Branch Name Author"

    def test_blank_author_is_treated_as_no_author(self):
        service = self._service(git_author="Branch Name Author")
        assert self._created_by(service, author="   ") == "Branch Name Author"

    def test_the_placeholder_is_the_last_resort(self):
        service = self._service(git_author=None)
        assert self._created_by(service, author=None) == PLACEHOLDER_AUTHOR_NAME

    def test_an_explicitly_chosen_name_is_never_second_guessed(self):
        # Previously the string "Developer" was used as a sentinel meaning
        # "unset", so a user who typed it got the git author instead.
        service = self._service(git_author="Branch Name Author")
        assert self._created_by(service, author=PLACEHOLDER_AUTHOR_NAME) == PLACEHOLDER_AUTHOR_NAME


class TestPreviewPanelAuthor:
    """The GUI gets the same treatment: `dat/gui/app.py` passes
    `configured_author_name`, so None has to mean "use git" there too."""

    def _git_info(self, author):
        return GitInfo(
            branch_name="feature/NSWM-1-add-toggle",
            inferred_title="NSWM-1 Add Toggle",
            ticket_id="NSWM-1",
            author_name=author,
        )

    def test_no_configured_name_falls_back_to_git(self):
        from dat.gui.state import GuiState

        state = GuiState.from_git_info(self._git_info("Branch Author"), author=None)
        assert state.author == "Branch Author"

    def test_a_configured_name_is_prefilled(self):
        from dat.gui.state import GuiState

        state = GuiState.from_git_info(self._git_info("Branch Author"), author="Priyansu Tandel")
        assert state.author == "Priyansu Tandel"

    def test_placeholder_only_when_nothing_is_known(self):
        from dat.gui.state import GuiState

        state = GuiState.from_git_info(self._git_info(None), author=None)
        assert state.author == PLACEHOLDER_AUTHOR_NAME


class TestConfigSetCommand:
    def _command(self, config_service, config=None):
        container = mock.Mock()
        container.config = config or DATConfig()
        container.configuration_service = config_service
        command = ConfigCommand(container=container)
        return command, container

    def _run(self, command, argv):
        return command.execute(vars(parse_args(argv)))

    def test_setting_the_author_name_persists_it(self, config_service, capsys):
        command, container = self._command(config_service)

        code = self._run(command, ["config", "set", "author-name", "Priyansu Tandel"])

        assert code == ExitCode.SUCCESS
        assert container.config.configured_author_name == "Priyansu Tandel"
        assert config_service.load_config().configured_author_name == "Priyansu Tandel"
        assert "Created By" in capsys.readouterr().out

    def test_setting_the_author_email_persists_it(self, config_service):
        command, container = self._command(config_service)

        code = self._run(command, ["config", "set", "author-email", "me@work.com"])

        assert code == ExitCode.SUCCESS
        assert container.config.configured_author_email == "me@work.com"
        assert config_service.load_config().configured_author_email == "me@work.com"

    def test_other_settings_are_writable_too(self, config_service):
        command, container = self._command(config_service)

        assert self._run(command, ["config", "set", "output-dir", "./out"]) == ExitCode.SUCCESS
        assert self._run(command, ["config", "set", "git-path", "/usr/bin/git"]) == ExitCode.SUCCESS
        assert container.config.default_output_dir == "./out"
        assert container.config.git_path == "/usr/bin/git"

    @pytest.mark.parametrize(
        "typed,expected",
        [
            ("author-name", "author-name"),
            ("author_name", "author-name"),
            ("author.name", "author-name"),
            ("AUTHOR-NAME", "author-name"),
            ("author", "author-name"),
            ("name", "author-name"),
            ("email", "author-email"),
            ("git", "git-path"),
            ("output", "output-dir"),
        ],
    )
    def test_keys_resolve_forgivingly(self, typed, expected):
        setting = find_setting(typed)
        assert setting is not None and setting.key == expected

    def test_an_unknown_key_is_rejected_without_saving(self, config_service, capsys):
        command, _ = self._command(config_service)

        code = self._run(command, ["config", "set", "favourite-colour", "blue"])

        assert code == ExitCode.VALIDATION_ERROR
        assert "Unknown setting" in capsys.readouterr().out
        assert not os.path.exists(config_service.config_file)

    def test_set_without_a_key_lists_the_options(self, config_service, capsys):
        command, _ = self._command(config_service)

        code = self._run(command, ["config", "set"])

        assert code == ExitCode.VALIDATION_ERROR
        assert "author-name" in capsys.readouterr().out

    def test_a_missing_value_prompts_when_there_is_a_terminal(self, config_service, monkeypatch):
        command, container = self._command(config_service)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _prompt="": "  Typed Name  ")

        code = self._run(command, ["config", "set", "author-name"])

        assert code == ExitCode.SUCCESS
        assert container.config.configured_author_name == "Typed Name"

    def test_an_empty_answer_at_the_prompt_changes_nothing(self, config_service, monkeypatch, capsys):
        command, container = self._command(config_service)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _prompt="": "")

        code = self._run(command, ["config", "set", "author-name"])

        assert code == ExitCode.SUCCESS
        assert container.config.configured_author_name is None
        assert "Unchanged" in capsys.readouterr().out

    def test_a_missing_value_without_a_terminal_is_an_error(self, config_service, monkeypatch, capsys):
        command, _ = self._command(config_service)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        def fail_input(_prompt=""):
            raise AssertionError("must not prompt without a terminal")

        monkeypatch.setattr("builtins.input", fail_input)

        code = self._run(command, ["config", "set", "author-name"])

        assert code == ExitCode.VALIDATION_ERROR
        assert "no terminal" in capsys.readouterr().out

    def test_a_save_failure_is_reported(self, config_service, monkeypatch, capsys):
        command, _ = self._command(config_service)
        monkeypatch.setattr(
            config_service, "save_config", mock.Mock(side_effect=OSError("read-only file system"))
        )

        code = self._run(command, ["config", "set", "author-name", "X"])

        assert code == ExitCode.CONFIGURATION_ERROR
        assert "read-only file system" in capsys.readouterr().out


class TestConfigShow:
    def _command(self, config_service, config, git_author="Git Name"):
        container = mock.Mock()
        container.config = config
        container.configuration_service = config_service
        container.git_service.get_git_info.return_value = GitInfo(
            branch_name="b", inferred_title="t", ticket_id=None, author_name=git_author
        )
        return ConfigCommand(container=container)

    def test_an_unset_author_explains_the_git_fallback(self, config_service, capsys):
        command = self._command(config_service, DATConfig())

        command.execute(vars(parse_args(["config"])))
        output = capsys.readouterr().out

        assert "not set" in output
        assert "Git Name" in output
        assert "dat config set author-name" in output

    def test_a_set_author_is_shown_plainly(self, config_service, capsys):
        config = DATConfig(author_name="Priyansu Tandel", author_name_set=True)
        command = self._command(config_service, config)

        command.execute(vars(parse_args(["config"])))
        output = capsys.readouterr().out

        assert "Priyansu Tandel" in output
        assert "not set - documents" not in output

    def test_the_git_lookup_failing_does_not_break_show(self, config_service, capsys):
        container = mock.Mock()
        container.config = DATConfig()
        container.configuration_service = config_service
        container.git_service.get_git_info.side_effect = RuntimeError("no git here")

        code = ConfigCommand(container=container).execute(vars(parse_args(["config"])))

        assert code == ExitCode.SUCCESS
        assert PLACEHOLDER_AUTHOR_NAME in capsys.readouterr().out
