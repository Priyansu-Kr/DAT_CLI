import subprocess
import os
from typing import List, Tuple, Optional
from dat.models.git_info import GitCommitInfo

class GitAdapter:
    def __init__(self, git_path: str = "git"):
        self.git_path = git_path

    def _run(self, args: List[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
        cmd = [self.git_path] + args
        try:
            res = subprocess.run(
                cmd,
                cwd=cwd or os.getcwd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except FileNotFoundError:
            return 127, "", "git binary not found"

    def is_git_repo(self, cwd: Optional[str] = None) -> bool:
        code, out, _ = self._run(["rev-parse", "--is-inside-work-tree"], cwd=cwd)
        return code == 0 and out == "true"

    def get_current_branch(self, cwd: Optional[str] = None) -> str:
        code, out, _ = self._run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
        if code == 0 and out:
            return out
        return "main"

    def get_repo_name(self, cwd: Optional[str] = None) -> str:
        code, out, _ = self._run(["rev-parse", "--show-toplevel"], cwd=cwd)
        if code == 0 and out:
            return os.path.basename(out)
        return os.path.basename(cwd or os.getcwd())

    def get_changed_files(self, cwd: Optional[str] = None) -> List[str]:
        code, out, _ = self._run(["status", "--porcelain"], cwd=cwd)
        files = []
        if code == 0 and out:
            for line in out.splitlines():
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2:
                    files.append(parts[1])
        if not files:
            code, out, _ = self._run(["diff", "--name-only", "HEAD~1", "HEAD"], cwd=cwd)
            if code == 0 and out:
                files = [line.strip() for line in out.splitlines() if line.strip()]
        return sorted(list(set(files)))

    def get_recent_commits(self, limit: int = 5, cwd: Optional[str] = None) -> List[GitCommitInfo]:
        format_str = "%H%n%an%n%ad%n%s%n---END---"
        code, out, _ = self._run(["log", f"-n{limit}", f"--pretty=format:{format_str}"], cwd=cwd)
        commits = []
        if code == 0 and out:
            blocks = out.split("---END---")
            for block in blocks:
                lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
                if len(lines) >= 4:
                    commits.append(GitCommitInfo(
                        hash=lines[0][:7],
                        author=lines[1],
                        date=lines[2],
                        message=lines[3]
                    ))
        return commits

    def get_raw_diff(self, cwd: Optional[str] = None) -> str:
        code, out, _ = self._run(["diff", "HEAD"], cwd=cwd)
        if code == 0 and out.strip():
            return out
        code, out, _ = self._run(["diff", "HEAD~1", "HEAD"], cwd=cwd)
        if code == 0 and out.strip():
            return out
        return ""
