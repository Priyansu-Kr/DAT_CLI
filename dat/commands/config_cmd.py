import sys
from typing import Dict, Any, Optional

from dat.commands.base import BaseCommand
from dat.models.config_model import DATConfig
from dat.utils.exit_codes import ExitCode


def describe_content_mode(cfg: DATConfig) -> str:
    """Which content pillar a document will be built from, in the user's terms."""
    if cfg.ai_api_key:
        return "Gemini AI (summary and test cases written from the branch diff)"
    return "Git diff (changed file names as 'Changes Done'; test cases left empty)"


class Setting:
    """One user-settable config value.

    `flag` names the companion `*_set` attribute where one exists: the author
    fields need "did the user choose this?" recorded separately from their
    value, because an unchosen name has to lose to the git author.
    """

    def __init__(self, key: str, attr: str, label: str, description: str, flag: Optional[str] = None):
        self.key = key
        self.attr = attr
        self.label = label
        self.description = description
        self.flag = flag


SETTINGS = [
    Setting(
        "author-name", "author_name", "Author name",
        "Shown as 'Created By' on every document DAT generates",
        flag="author_name_set",
    ),
    Setting(
        "author-email", "author_email", "Author email",
        "Stored for reference and exposed to MCP clients; not printed in documents",
        flag="author_email_set",
    ),
    Setting("output-dir", "default_output_dir", "Default output dir", "Where generated documents are written"),
    Setting("git-path", "git_path", "Git binary path", "Use if 'git' isn't on your PATH"),
]


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("_", "-").replace(".", "-")


def find_setting(key: str) -> Optional[Setting]:
    normalized = _normalize_key(key)
    for setting in SETTINGS:
        if normalized == setting.key or normalized == setting.attr.replace("_", "-"):
            return setting
    # Forgiving aliases: 'author', 'name', 'email' are what people type.
    aliases = {
        "author": "author-name",
        "name": "author-name",
        "email": "author-email",
        "mail": "author-email",
        "output": "output-dir",
        "outputdir": "output-dir",
        "docs-dir": "output-dir",
        "git": "git-path",
    }
    target = aliases.get(normalized)
    if target:
        return next(s for s in SETTINGS if s.key == target)
    return None


class ConfigCommand(BaseCommand):
    def execute(self, args: Dict[str, Any]) -> ExitCode:
        action = args.get("action") or "show"

        if action == "set":
            return self._set(args.get("key"), args.get("value"))

        cfg = self.container.config

        if action == "init":
            self.container.configuration_service.save_config(cfg)
            print(f"[SUCCESS] Config initialized at {self.container.configuration_service.config_file}")
            if not cfg.configured_author_name:
                print("Set the name your documents should carry:")
                print('  dat config set author-name "Your Name"')
            return ExitCode.SUCCESS

        print(f"\n--- DAT Configuration ({self.container.configuration_service.config_file}) ---")
        print(f"Author Name        : {self._describe_author_name(cfg)}")
        print(f"Author Email       : {self._describe_author_email(cfg)}")
        print(f"Default Output Dir : {cfg.default_output_dir}")
        print(f"Git Binary Path    : {cfg.git_path}")
        print(f"AI Provider        : {cfg.ai_provider}")
        print(f"Gemini API Key     : {'saved' if cfg.ai_api_key else 'not saved'}")
        print(f"Document Content   : {describe_content_mode(cfg)}")
        print("------------------------------------------")

        print("Change any of these with:")
        for setting in SETTINGS:
            print(f"  dat config set {setting.key} <value>".ljust(42) + f"# {setting.description}")
        if not cfg.ai_api_key:
            print("Run 'dat save-api-key' to enable AI-written summaries and test cases.")
        print()
        return ExitCode.SUCCESS

    def _describe_author_name(self, cfg: DATConfig) -> str:
        configured = cfg.configured_author_name
        if configured:
            source = "from $DAT_AUTHOR" if configured == self._env_author() else "used on documents"
            return f"{configured}  ({source})"
        git_author = self._git_author()
        if git_author:
            return f"not set - documents use your git name, '{git_author}'"
        return "not set - documents fall back to 'Developer'"

    def _describe_author_email(self, cfg: DATConfig) -> str:
        return cfg.configured_author_email or "not set"

    def _env_author(self) -> Optional[str]:
        import os

        return os.getenv("DAT_AUTHOR")

    def _git_author(self) -> Optional[str]:
        """The name git would supply, for the 'not set' explanation."""
        try:
            return self.container.git_service.get_git_info().author_name or None
        except Exception:
            return None

    def _set(self, key: Optional[str], value: Optional[str]) -> ExitCode:
        if not key:
            print("\nWhich setting? Usage: dat config set <key> <value>\n")
            for setting in SETTINGS:
                print(f"  {setting.key:<14} {setting.description}")
            print()
            return ExitCode.VALIDATION_ERROR

        setting = find_setting(key)
        if setting is None:
            print(f"\nUnknown setting: {key}")
            print("Valid keys: " + ", ".join(s.key for s in SETTINGS) + "\n")
            return ExitCode.VALIDATION_ERROR

        cfg = self.container.config

        if value is None:
            current = getattr(cfg, setting.attr, "")
            if not sys.stdin.isatty():
                print(f"\nNo value given for {setting.key}, and there's no terminal to ask on.")
                print(f'Usage: dat config set {setting.key} "<value>"\n')
                return ExitCode.VALIDATION_ERROR
            try:
                value = input(f"{setting.label} [{current}]: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return ExitCode.SUCCESS
            if not value:
                print(f"Unchanged - {setting.label} is still '{current}'.")
                return ExitCode.SUCCESS

        value = value.strip()
        if not value:
            print(f"\n{setting.label} cannot be empty.\n")
            return ExitCode.VALIDATION_ERROR

        setattr(cfg, setting.attr, value)
        if setting.flag:
            setattr(cfg, setting.flag, True)

        try:
            self.container.configuration_service.save_config(cfg)
        except Exception as exc:
            print(f"\n[Error] Could not save the config: {exc}\n")
            return ExitCode.CONFIGURATION_ERROR

        print(f"\n{setting.label} set to: {value}")
        print(f"Saved to {self.container.configuration_service.config_file}")
        if setting.attr == "author_name":
            print("Documents generated from now on will show this as 'Created By'.")
        print()
        return ExitCode.SUCCESS
