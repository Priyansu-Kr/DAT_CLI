from typing import Dict, Any
from dat.commands.base import BaseCommand
from dat.models.config_model import DATConfig
from dat.utils.exit_codes import ExitCode


def describe_content_mode(cfg: DATConfig) -> str:
    """Which content pillar a document will be built from, in the user's terms."""
    if cfg.ai_api_key:
        return "Gemini AI (summary and test cases written from the branch diff)"
    return "Git diff (changed file names as 'Changes Done'; test cases left empty)"

class ConfigCommand(BaseCommand):
    def execute(self, args: Dict[str, Any]) -> ExitCode:
        cfg = self.container.config
        action = args.get("action", "show")

        if action == "init":
            self.container.configuration_service.save_config(cfg)
            print(f"[SUCCESS] Config initialized at {self.container.configuration_service.config_file}")
            return ExitCode.SUCCESS

        print(f"\n--- DAT Configuration ({self.container.configuration_service.config_file}) ---")
        print(f"Author Name        : {cfg.author_name}")
        print(f"Author Email       : {cfg.author_email}")
        print(f"Default Output Dir : {cfg.default_output_dir}")
        print(f"Git Binary Path    : {cfg.git_path}")
        print(f"AI Provider        : {cfg.ai_provider}")
        print(f"Gemini API Key     : {'saved' if cfg.ai_api_key else 'not saved'}")
        print(f"Document Content   : {describe_content_mode(cfg)}")
        print("------------------------------------------")
        if not cfg.ai_api_key:
            print("Run 'dat save-api-key' to enable AI-written summaries and test cases.")
        print()
        return ExitCode.SUCCESS
