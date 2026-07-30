import re
from typing import Optional, List, Tuple
from dat.adapters.git_adapter import GitAdapter
from dat.models.git_info import GitInfo

class GitService:
    def __init__(self, git_adapter: Optional[GitAdapter] = None):
        self.adapter = git_adapter or GitAdapter()

    def get_git_info(self, cwd: Optional[str] = None) -> GitInfo:
        if not self.adapter.is_git_repo(cwd):
            return GitInfo(
                branch_name="standalone-repo",
                inferred_title="Software Feature Documentation",
                ticket_id=None,
                author_name="Developer",
                repo_name=self.adapter.get_repo_name(cwd),
                changed_files=[],
                recent_commits=[],
                raw_diff=""
            )

        branch_name = self.adapter.get_current_branch(cwd)
        inferred_title, ticket_id, author_name = self.parse_branch_name(branch_name)
        repo_name = self.adapter.get_repo_name(cwd)
        changed_files = self.adapter.get_changed_files(cwd)
        recent_commits = self.adapter.get_recent_commits(limit=5, cwd=cwd)
        raw_diff = self.adapter.get_raw_diff(cwd)

        return GitInfo(
            branch_name=branch_name,
            inferred_title=inferred_title,
            ticket_id=ticket_id,
            author_name=author_name,
            repo_name=repo_name,
            changed_files=changed_files,
            recent_commits=recent_commits,
            raw_diff=raw_diff
        )

    def parse_branch_name(self, branch_name: str) -> Tuple[str, Optional[str], Optional[str]]:
        # Example input: feature/NSWM-6374-Priyansu-Kumar-Add-Bin-Ward-Enable-Disable-Toggle-in-Collector-App
        
        # 1. Strip branch prefix
        clean_branch = re.sub(r'^(feature|fix|bugfix|chore|refactor|hotfix|release)/', '', branch_name, flags=re.IGNORECASE)
        
        # 2. Extract Ticket ID (e.g., NSWM-6374)
        ticket_match = re.search(r'([A-Z]{2,10}[-_]\d+)', clean_branch, flags=re.IGNORECASE)
        ticket_id = ticket_match.group(1).upper().replace('_', '-') if ticket_match else None
        
        # 3. Extract Topic and remove Author
        remaining = clean_branch
        if ticket_id:
            remaining = re.sub(re.escape(ticket_id), '', clean_branch, flags=re.IGNORECASE).strip('-')
        
        parts = remaining.split('-')
        
        # Heuristic: Find the first common action verb to determine where the topic starts
        action_verbs = {'add', 'fix', 'update', 'remove', 'implement', 'feature', 'refactor', 'bug', 'change', 'persist', 'toggle'}
        start_idx = 0
        author_parts = []
        for i, p in enumerate(parts):
            if p.lower() in action_verbs:
                start_idx = i
                break
            author_parts.append(p)
        else:
            if len(parts) > 2:
                start_idx = 2
                author_parts = parts[:2]
            elif len(parts) > 1:
                start_idx = 1
                author_parts = parts[:1]

        topic_parts = parts[start_idx:]
        topic = " ".join(topic_parts)
        
        # Format Author Name
        author_name = " ".join([p.capitalize() for p in author_parts]) if author_parts else None
        
        # Final cleaning: Handle CamelCase if any
        topic = re.sub(r'([a-z])([A-Z])', r'\1 \2', topic).strip()
        
        # Result: "NSWM-6374 Add Bin Ward..."
        full_title = f"{ticket_id} {topic}" if ticket_id else topic
        return full_title, ticket_id, author_name
