from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class GitCommitInfo:
    hash: str
    author: str
    date: str
    message: str

@dataclass
class GitInfo:
    branch_name: str
    inferred_title: str
    ticket_id: Optional[str] = None
    author_name: Optional[str] = None
    repo_name: Optional[str] = None
    changed_files: List[str] = field(default_factory=list)
    recent_commits: List[GitCommitInfo] = field(default_factory=list)
    raw_diff: str = ""
