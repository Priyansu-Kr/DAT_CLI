from typing import List, Optional
from dat.adapters.ai_adapter import AIAdapter, build_git_diff_summary
from dat.models.doc_request import ChangeSummary
from dat.models.git_info import GitInfo


def default_change_summary(
    title: Optional[str] = None, changed_files: Optional[List[str]] = None
) -> ChangeSummary:
    """Fallback content used whenever summary generation fails outright, so
    callers always have something sensible to show/export rather than an
    empty gap.

    Where the changed files are known this is exactly the Git-diff pillar's
    output - real file names beat invented bullet points. Only a caller with
    nothing at all to go on gets the "fill this in" placeholder."""
    if changed_files:
        return build_git_diff_summary(title or "these changes", changed_files)

    return ChangeSummary(
        overview=f"Summary unavailable for '{title}' - please fill in the details manually." if title
        else "Summary unavailable - please fill in the details manually.",
        key_points=[],
        impact_areas=[],
        test_recommendations=[],
        test_cases=[],
    )


class AIService:
    def __init__(self, ai_adapter: Optional[AIAdapter] = None):
        self.adapter = ai_adapter or AIAdapter()

    def generate_change_summary(self, git_info: GitInfo) -> ChangeSummary:
        # AIAdapter already falls back to a rule-based summary if the AI
        # provider fails, but guard here too so a truly unexpected error
        # (bad git_info, adapter misconfiguration, etc.) still yields
        # usable default data instead of propagating a crash.
        try:
            commit_msgs = [c.message for c in git_info.recent_commits]
            return self.adapter.generate_summary(
                title=git_info.inferred_title,
                changed_files=git_info.changed_files,
                commits=commit_msgs,
                raw_diff=git_info.raw_diff
            )
        except Exception as e:
            print(f"[Warning] AI summary generation failed, using defaults: {e}")
            return default_change_summary(
                getattr(git_info, "inferred_title", None),
                getattr(git_info, "changed_files", None),
            )
