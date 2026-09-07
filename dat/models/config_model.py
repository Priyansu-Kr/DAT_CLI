from dataclasses import dataclass, field
from typing import Dict, Any, Optional

# The three ways DAT can fill a document's content - the toolkit's "pillars":
#   gemini    - summaries authored by the Gemini API from the branch diff
#   git-diff  - no AI at all: the changed file names are the content, and
#               test cases are left for the user to write (chosen when the
#               user answers "no" to the API-key question)
#   An LLM/agent driving the MCP server is the third path; it hands over
#   finished content through a seed file, so no provider setting applies.
AI_PROVIDER_GEMINI = "gemini"
AI_PROVIDER_GIT_DIFF = "git-diff"

# What ai_provider holds before the user has been asked which they want.
AI_PROVIDER_UNSET = "rule-based"


def ai_choice_made(provider: Optional[str], api_key: Optional[str]) -> bool:
    """Whether the user has already settled how content gets generated, so
    the API-key question must not be asked again."""
    return bool(api_key) or provider == AI_PROVIDER_GIT_DIFF


# Stand-ins, not answers: they exist so a document always has *something* in
# its "Created By" row, and they are what `author_name_set` / `author_email_set`
# below are False against. Nothing should ever write these to a document in
# preference to a real name from git.
PLACEHOLDER_AUTHOR_NAME = "Developer"
PLACEHOLDER_AUTHOR_EMAIL = "developer@example.com"


@dataclass
class DATConfig:
    author_name: str = PLACEHOLDER_AUTHOR_NAME
    author_email: str = PLACEHOLDER_AUTHOR_EMAIL
    default_output_dir: str = "./docs"
    git_path: str = "git"
    ai_provider: str = AI_PROVIDER_UNSET
    ai_api_key: Optional[str] = None
    # True when the key came from $DAT_AI_KEY rather than the config file.
    # Such a key is the environment's to own: DAT uses it, but never copies
    # it onto disk behind the user's back.
    ai_key_from_env: bool = False
    # Whether the user actually chose an author, as opposed to inheriting the
    # placeholder above. Kept separate because "is there a name?" and "which
    # name?" are different questions: an unset name must lose to the git
    # author, while a set one must win over it.
    author_name_set: bool = False
    author_email_set: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def configured_author_name(self) -> Optional[str]:
        """The author the user chose, or None to mean "fall back to git"."""
        name = (self.author_name or "").strip()
        return name if self.author_name_set and name else None

    @property
    def configured_author_email(self) -> Optional[str]:
        email = (self.author_email or "").strip()
        return email if self.author_email_set and email else None
