from dataclasses import dataclass, field
from typing import Dict, Any, Optional

@dataclass
class DATConfig:
    author_name: str = "Developer"
    author_email: str = "developer@example.com"
    default_output_dir: str = "./docs"
    git_path: str = "git"
    ai_provider: str = "rule-based"
    ai_api_key: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
