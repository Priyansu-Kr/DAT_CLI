from typing import List, Optional
from dat.adapters.ai_adapter import AIAdapter
from dat.models.doc_request import ChangeSummary
from dat.models.git_info import GitInfo

class AIService:
    def __init__(self, ai_adapter: Optional[AIAdapter] = None):
        self.adapter = ai_adapter or AIAdapter()

    def generate_change_summary(self, git_info: GitInfo) -> ChangeSummary:
        commit_msgs = [c.message for c in git_info.recent_commits]
        return self.adapter.generate_summary(
            title=git_info.inferred_title,
            changed_files=git_info.changed_files,
            commits=commit_msgs,
            raw_diff=git_info.raw_diff
        )
