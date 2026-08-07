import os
import subprocess
from typing import List, Optional, Tuple

from dat.models.git_info import GitCommitInfo

# Branches a feature branch is normally cut from, most likely first. The
# merge-base against the first one that exists is what makes "the work on
# this branch" mean every commit since it diverged, rather than just the
# latest commit.
BASE_BRANCH_CANDIDATES: Tuple[str, ...] = (
    "origin/main", "origin/master", "origin/develop", "main", "master", "develop",
)

# Commits to report when a branch range is available. Generous, because they
# are one line each and describe the whole feature.
BRANCH_COMMIT_LIMIT = 25
# Commits to report when there is no range to work with (e.g. on main).
FALLBACK_COMMIT_LIMIT = 5

# Per-file caps for synthesising a diff for brand-new (untracked) files.
# Untracked content is read by us rather than by git, so these bound the work
# before the AI-side budget does any further trimming.
UNTRACKED_MAX_BYTES = 200_000
UNTRACKED_BINARY_SNIFF_BYTES = 8_000


def _unquote_path(path: str) -> str:
    """Undo git's C-style quoting of paths with spaces/specials/unicode."""
    if len(path) >= 2 and path.startswith('"') and path.endswith('"'):
        inner = path[1:-1]
        try:
            return inner.encode("latin-1", "backslashreplace").decode("unicode_escape")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return inner
    return path


def parse_porcelain_line(line: str) -> Optional[Tuple[str, str]]:
    """Split one `git status --porcelain` line into (status, path).

    Handles the two shapes that a naive whitespace split gets wrong: renames
    and copies ("R  old -> new", where the destination is the current path),
    and quoted paths.
    """
    if len(line) < 4:
        return None
    status, path = line[:2], line[3:]
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    path = _unquote_path(path.strip())
    return (status, path) if path else None


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

    # --- Status ----------------------------------------------------------

    def _status_entries(self, cwd: Optional[str] = None) -> List[Tuple[str, str]]:
        """Working-tree status. `-uall` lists untracked *files* rather than
        collapsing them into a directory entry."""
        code, out, _ = self._run(["status", "--porcelain", "-uall"], cwd=cwd)
        if code != 0 or not out:
            return []
        entries = []
        for line in out.splitlines():
            parsed = parse_porcelain_line(line)
            if parsed:
                entries.append(parsed)
        return entries

    def get_untracked_files(self, cwd: Optional[str] = None) -> List[str]:
        return [path for status, path in self._status_entries(cwd) if status == "??"]

    def get_changed_files(self, cwd: Optional[str] = None) -> List[str]:
        files = [path for _status, path in self._status_entries(cwd)]
        if not files:
            base = self.get_base_ref(cwd)
            revision_range = f"{base}..HEAD" if base else "HEAD~1..HEAD"
            code, out, _ = self._run(["diff", "--name-only", revision_range], cwd=cwd)
            if code == 0 and out:
                files = [line.strip() for line in out.splitlines() if line.strip()]
        return sorted(set(files))

    # --- History ---------------------------------------------------------

    def get_base_ref(self, cwd: Optional[str] = None) -> Optional[str]:
        """Commit where this branch diverged from its base branch.

        None when that can't be established - no base branch exists, or we
        are on the base branch itself - in which case callers fall back to
        the previous commit.
        """
        current = self.get_current_branch(cwd)
        code, head, _ = self._run(["rev-parse", "HEAD"], cwd=cwd)
        head = head if code == 0 else ""

        for candidate in BASE_BRANCH_CANDIDATES:
            if candidate.split("/")[-1] == current:
                continue  # we *are* the base branch; nothing to diverge from
            code, _out, _ = self._run(["rev-parse", "--verify", "--quiet", candidate], cwd=cwd)
            if code != 0:
                continue
            code, base, _ = self._run(["merge-base", "HEAD", candidate], cwd=cwd)
            if code != 0 or not base or base == head:
                continue
            return base
        return None

    def get_recent_commits(
        self,
        limit: int = FALLBACK_COMMIT_LIMIT,
        cwd: Optional[str] = None,
        revision_range: Optional[str] = None,
    ) -> List[GitCommitInfo]:
        format_str = "%H%n%an%n%ad%n%s%n---END---"
        args = ["log", f"-n{limit}", f"--pretty=format:{format_str}"]
        if revision_range:
            args.append(revision_range)
        code, out, _ = self._run(args, cwd=cwd)
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

    def get_branch_commits(self, cwd: Optional[str] = None) -> List[GitCommitInfo]:
        """Commits belonging to this branch, or the most recent few if the
        branch point can't be determined."""
        base = self.get_base_ref(cwd)
        if base:
            commits = self.get_recent_commits(
                limit=BRANCH_COMMIT_LIMIT, cwd=cwd, revision_range=f"{base}..HEAD"
            )
            if commits:
                return commits
        return self.get_recent_commits(limit=FALLBACK_COMMIT_LIMIT, cwd=cwd)

    # --- Diff ------------------------------------------------------------

    def get_raw_diff(self, cwd: Optional[str] = None) -> str:
        """The code under review, as a unified diff.

        Preference order, so the AI sees the work actually being documented:

        1. Uncommitted changes (`git diff HEAD`) plus the content of new,
           untracked files - which `git diff` never shows.
        2. Everything committed on this branch (`<merge-base>..HEAD`), so a
           feature spread over several commits is covered rather than just
           the last one.
        3. The previous commit alone, when there is no branch point to
           measure from.
        """
        code, tracked, _ = self._run(["diff", "HEAD"], cwd=cwd)
        tracked = tracked if code == 0 else ""
        untracked = self.get_untracked_diff(cwd=cwd)
        if tracked.strip() or untracked.strip():
            return "\n".join(part for part in (tracked, untracked) if part.strip())

        base = self.get_base_ref(cwd)
        if base:
            code, out, _ = self._run(["diff", f"{base}..HEAD"], cwd=cwd)
            if code == 0 and out.strip():
                return out

        code, out, _ = self._run(["diff", "HEAD~1", "HEAD"], cwd=cwd)
        if code == 0 and out.strip():
            return out
        return ""

    def get_untracked_diff(self, cwd: Optional[str] = None) -> str:
        """Synthesise an add-everything diff for untracked files.

        `git diff` only reports tracked content, so without this a brand-new
        file (a new screen, class or module) is named in the file list while
        its code never reaches the summary. Built by reading the files here
        rather than with `git add -N`, which would mutate the user's index.
        """
        root = cwd or os.getcwd()
        sections: List[str] = []

        for path in self.get_untracked_files(cwd=cwd):
            absolute = os.path.join(root, path)
            content = self._read_text_file(absolute)
            if content is None:
                continue
            lines = content.splitlines()
            body = "\n".join(f"+{line}" for line in lines)
            sections.append(
                f"diff --git a/{path} b/{path}\n"
                f"new file mode 100644\n"
                f"--- /dev/null\n"
                f"+++ b/{path}\n"
                f"@@ -0,0 +1,{len(lines)} @@\n"
                f"{body}"
            )

        return "\n".join(sections)

    @staticmethod
    def _read_text_file(path: str) -> Optional[str]:
        """File content, or None when it isn't usable as diff text (missing,
        unreadable, binary, or too large to be worth sending)."""
        try:
            if os.path.getsize(path) > UNTRACKED_MAX_BYTES:
                return None
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            return None

        if b"\x00" in raw[:UNTRACKED_BINARY_SNIFF_BYTES]:
            return None  # binary: an image or archive, not reviewable text
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
