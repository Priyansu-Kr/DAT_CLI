import os
import yaml
from typing import Optional
from dat.models.config_model import DATConfig
from dat.adapters.filesystem_adapter import FilesystemAdapter

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
                    if "author_name" in data: config.author_name = str(data["author_name"])
                    if "author_email" in data: config.author_email = str(data["author_email"])
                    if "default_output_dir" in data: config.default_output_dir = str(data["default_output_dir"])
                    if "git_path" in data: config.git_path = str(data["git_path"])
                    if "ai_provider" in data: config.ai_provider = str(data["ai_provider"])
                    if "ai_api_key" in data: config.ai_api_key = str(data["ai_api_key"])
                    config.extra = data
            except Exception:
                pass
        
        if os.getenv("DAT_AUTHOR"): config.author_name = os.getenv("DAT_AUTHOR")
        if os.getenv("DAT_AI_KEY"): config.ai_api_key = os.getenv("DAT_AI_KEY")

        return config

    def save_config(self, config: DATConfig) -> None:
        self.fs.ensure_dir(self.config_dir)
        data = {
            "author_name": config.author_name,
            "author_email": config.author_email,
            "default_output_dir": config.default_output_dir,
            "git_path": config.git_path,
            "ai_provider": config.ai_provider,
        }
        if config.ai_api_key:
            data["ai_api_key"] = config.ai_api_key
        
        content = yaml.dump(data, default_flow_style=False)
        self.fs.write_text(self.config_file, content)
