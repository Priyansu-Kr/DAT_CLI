from typing import Dict, Any
from dat.commands.base import BaseCommand
from dat.utils.exit_codes import ExitCode

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
        print("------------------------------------------\n")
        return ExitCode.SUCCESS
