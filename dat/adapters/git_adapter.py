import fnmatch
import os
import subprocess
import sys
from typing import Iterable, List, Optional, Tuple

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

# Untracked files are read by DAT itself and their *entire contents* go into
# the AI prompt - which, with a Gemini key configured, means leaving the
# machine. Git never had a say: these files are not in the repository, so no
# reviewer ever approved them being shared. This list is therefore a privacy
# boundary rather than a tidiness one, and it errs towards excluding: a file
# skipped here is merely absent from the AI's context (untracked files are not
# listed in "Changes Done" either way), while a file wrongly included is a
# credential posted to a third-party API.
SENSITIVE_FILE_PATTERNS: Tuple[str, ...] = (
    # Environment files and anything self-describing as a secret
    ".env", ".env.*", "*.env",
    "*credential*", "*secret*", "*password*", "*passwd*", "*.token",
    ".netrc", "_netrc", ".npmrc", ".pypirc", ".pgpass", ".htpasswd",
    # Private keys, certificates and keystores
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.ppk",
    "*.crt", "*.cer", "*.der", "*.asc", "*.gpg", "*.kdbx",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    # Service descriptors that embed live API keys
    "google-services.json", "googleservice-info.plist",
    "serviceaccount*.json", "*-adminsdk-*.json",
    "local.properties", "kubeconfig", "*.kubeconfig",
    # Terraform state stores resolved secrets in plaintext
    "terraform.tfstate", "terraform.tfstate.*",
)

# Files that are neither secret nor reviewable code - generated output, editor
# and OS droppings, dependency lock files. Excluded to keep the prompt (and
# its character budget) for code that a reader would actually document.
NOISE_FILE_PATTERNS: Tuple[str, ...] = (
    "*.log", "*.tmp", "*.temp", "*.bak", "*.orig", "*.rej", "*.swp", "*.swo",
    "*.min.js", "*.min.css", "*.map",
    "*.lock", "*-lock.json", "*.lock.json", "yarn.lock", "pnpm-lock.yaml",
    ".ds_store", "thumbs.db",
)

# Extra globs a team can add for repo-specific files, comma-separated:
#   export DAT_UNTRACKED_EXCLUDE="fixtures/*.json,*.internal"
UNTRACKED_EXCLUDE_ENV = "DAT_UNTRACKED_EXCLUDE"


def _extra_exclude_patterns() -> Tuple[str, ...]:
    raw = os.environ.get(UNTRACKED_EXCLUDE_ENV, "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    """Glob-match a repo-relative path against `patterns`.

    Each pattern is tried against both the bare filename and the full path,
    so "local.properties" catches it in any directory while "config/*.json"
    can target one. Matching is case-folded because the same checked-in file
    is `.ENV` on one developer's Windows box and `.env` on another's Linux.
    """
    posix = path.replace("\\", "/").lower()
    basename = posix.rsplit("/", 1)[-1]
    return any(
        fnmatch.fnmatchcase(basename, pattern) or fnmatch.fnmatchcase(posix, pattern)
        for pattern in (p.lower() for p in patterns)
    )


def untracked_skip_reason(path: str) -> Optional[str]:
    """Why this untracked file must not be read, or None to read it.

    Ordered so the privacy rule is reported ahead of the tidiness one - the
    two have very different consequences and the message says which applied.
    """
    if _matches_any(path, SENSITIVE_FILE_PATTERNS):
        return "looks like a credential or local configuration"
    if _matches_any(path, _extra_exclude_patterns()):
        return f"excluded by ${UNTRACKED_EXCLUDE_ENV}"
    if _matches_any(path, NOISE_FILE_PATTERNS):
        return "generated or editor file, not reviewable source"
    return None

# `git status --porcelain` codes that mark a file as work worth documenting:
# modified, added, renamed, copied, unmerged and type-changed. Untracked
# ("??") and ignored ("!!") files are excluded on purpose - a scratch note or
# a local .env sitting in the tree is not part of the change being written up.
WORK_STATUS_CODES = frozenset("MARCUT")

# The same idea expressed for `git diff`: everything except deletions.
DIFF_WORK_FILTER = "--diff-filter=ACMRT"


def is_work_status(status: str) -> bool:
    """Whether a porcelain status code means "this file is changed work".

    Deletions fail this test in either column: a file that no longer exists
    has nothing to show in a document, and "Changes Done" listing a name the
    reader cannot open is worse than not listing it. Untracked files fail it
    too - they are indistinguishable from local clutter until git tracks them.
    """
    if status in ("??", "!!") or "D" in status:
        return False
    return any(code in WORK_STATUS_CODES for code in status)


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

    def _run(
        self, args: List[str], cwd: Optional[str] = None, strip: bool = True
    ) -> Tuple[int, str, str]:
        """Run a git command. `strip=False` for output whose leading
        whitespace is data - `status --porcelain` encodes the worktree state
        in columns 1-2, so stripping would silently shift the first line."""
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
            out = res.stdout.strip() if strip else res.stdout.rstrip("\n")
            return res.returncode, out, res.stderr.strip()
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
        code, out, _ = self._run(["status", "--porcelain", "-uall"], cwd=cwd, strip=False)
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

    def _range_changed_files(
        self, revision_range: str, cwd: Optional[str] = None
    ) -> List[str]:
        """Files a commit range modified or added, deletions filtered out."""
        code, out, _ = self._run(
            ["diff", "--name-only", DIFF_WORK_FILTER, revision_range], cwd=cwd
        )
        if code != 0 or not out:
            return []
        return [line.strip() for line in out.splitlines() if line.strip()]

    def get_changed_files(self, cwd: Optional[str] = None) -> List[str]:
        """The files this piece of work modified or added.

        Two sources, because a branch is normally *both* committed and still
        in progress, and a document about it needs the whole picture:

        1. Every commit since the branch point - work that is already
           committed does not stop being part of the change.
        2. Modifications and additions sitting in the working tree, staged
           or not.

        Untracked files and deletions are excluded from both (see
        `is_work_status`), and a file deleted in the working tree is removed
        even when an earlier commit on the branch touched it - the end state
        of the branch is what gets documented, not every intermediate step.
        """
        entries = self._status_entries(cwd)
        worktree = {path for status, path in entries if is_work_status(status)}
        deleted = {path for status, path in entries if "D" in status}

        base = self.get_base_ref(cwd)
        if base:
            committed = set(self._range_changed_files(f"{base}..HEAD", cwd))
        elif not worktree:
            # No branch point to measure from (typically: we are *on* main).
            # The previous commit is then the only work there is to describe,
            # and only when nothing uncommitted has superseded it - otherwise
            # an unrelated commit by someone else lands in the document.
            committed = set(self._range_changed_files("HEAD~1..HEAD", cwd))
        else:
            committed = set()

        return sorted((committed | worktree) - deleted)

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

        Files that look like credentials or local configuration are never
        read - see `untracked_skip_reason`. To include one deliberately,
        `git add` it: staged content reaches the AI through `git diff HEAD`,
        which makes sharing it an explicit act rather than a side effect of
        it happening to sit in the folder.
        """
        root = cwd or os.getcwd()
        sections: List[str] = []
        skipped: List[Tuple[str, str]] = []

        for path in self.get_untracked_files(cwd=cwd):
            reason = untracked_skip_reason(path)
            if reason:
                skipped.append((path, reason))
                continue

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

        self._report_skipped_untracked(skipped)
        return "\n".join(sections)

    @staticmethod
    def _report_skipped_untracked(skipped: List[Tuple[str, str]]) -> None:
        """Say what was withheld and why.

        Silently dropping a file the developer expected to be summarised is
        the one failure mode this filter can cause, so it is never silent.
        Written to stderr: stdout belongs to the MCP server's JSON-RPC stream.
        """
        if not skipped:
            return
        print(
            f"[DAT] {len(skipped)} untracked file(s) were not sent to the AI:",
            file=sys.stderr,
        )
        for path, reason in skipped:
            print(f"       {path} - {reason}", file=sys.stderr)
        print(
            "       `git add <file>` to include one deliberately.",
            file=sys.stderr,
        )

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
