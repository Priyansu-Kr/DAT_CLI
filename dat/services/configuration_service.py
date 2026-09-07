import os
import yaml
from typing import Optional
from dat.models.config_model import (
    DATConfig,
    PLACEHOLDER_AUTHOR_EMAIL,
    PLACEHOLDER_AUTHOR_NAME,
)
from dat.adapters.filesystem_adapter import FilesystemAdapter

# rw for the owner only (a no-op on filesystems without POSIX permissions).
CONFIG_FILE_MODE = 0o600


class ConfigurationService:
    def __init__(self, fs: Optional[FilesystemAdapter] = None):
        self.fs = fs or FilesystemAdapter()
        self.config_dir = os.path.expanduser("~/.dat")
        self.config_file = os.path.join(self.config_dir, "config.yaml")

    def load_config(self) -> DATConfig:
        config = DATConfig()
        if self.fs.exists(self.config_file):
            try:
                content = self.fs.read_text(self.config_file)
                data = yaml.safe_load(content) or {}
                if isinstance(data, dict):
                    # A value equal to the placeholder counts as *unset*, not
                    # as a choice. Config files written by earlier versions
                    # always contained `author_name: Developer` because
                    # `config init` saved the defaults, and treating those as
                    # deliberate would make every one of those users' documents
                    # say "Developer" instead of their git name. (Someone whose
                    # name really is "Developer" falls back to their git author,
                    # which will say the same thing.)
                    if "author_name" in data:
                        config.author_name = str(data["author_name"])
                        config.author_name_set = config.author_name.strip() not in (
                            "", PLACEHOLDER_AUTHOR_NAME,
                        )
                    if "author_email" in data:
                        config.author_email = str(data["author_email"])
                        config.author_email_set = config.author_email.strip() not in (
                            "", PLACEHOLDER_AUTHOR_EMAIL,
                        )
                    if "default_output_dir" in data: config.default_output_dir = str(data["default_output_dir"])
                    if "git_path" in data: config.git_path = str(data["git_path"])
                    if "ai_provider" in data: config.ai_provider = str(data["ai_provider"])
                    if "ai_api_key" in data: config.ai_api_key = str(data["ai_api_key"])
                    config.extra = data
            except Exception:
                pass
        
        if os.getenv("DAT_AUTHOR"):
            config.author_name = os.getenv("DAT_AUTHOR")
            config.author_name_set = True
        if os.getenv("DAT_AI_KEY"):
            config.ai_api_key = os.getenv("DAT_AI_KEY")
            config.ai_key_from_env = True

        return config

    def save_config(self, config: DATConfig) -> None:
        self.fs.ensure_dir(self.config_dir)
        data = {
            "default_output_dir": config.default_output_dir,
            "git_path": config.git_path,
            "ai_provider": config.ai_provider,
        }
        # Only a name the user actually chose is written. Persisting the
        # placeholder would make the file indistinguishable from a deliberate
        # choice on the next load, which is exactly the ambiguity that made
        # older configs override the git author.
        if config.configured_author_name:
            data["author_name"] = config.configured_author_name
        if config.configured_author_email:
            data["author_email"] = config.configured_author_email
        # A key supplied through $DAT_AI_KEY is not ours to write down - saving
        # it would leave a copy on disk that outlives the environment that set
        # it, and that the user never asked us to store.
        if config.ai_api_key and not config.ai_key_from_env:
            data["ai_api_key"] = config.ai_api_key
        
        content = yaml.dump(data, default_flow_style=False)
        # Owner-only: this file can hold an API key, and the default 0644 would
        # expose it to every other account on a shared machine.
        self.fs.write_text(self.config_file, content, mode=CONFIG_FILE_MODE)
