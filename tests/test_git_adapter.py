"""How DAT decides what code is under review.

The adapter is driven through a fake `_run`, so these assert the exact git
commands issued and how their output is interpreted - no real repository or
network required.
"""
import contextlib
import io
import os
import tempfile
import unittest
from typing import Dict, List, Optional, Tuple
from unittest import mock

from dat.adapters.git_adapter import (
    GitAdapter,
    is_work_status,
    parse_porcelain_line,
    untracked_skip_reason,
)


class FakeGit(GitAdapter):
    """GitAdapter with `_run` replaced by a scripted responder."""

    def __init__(self, responses: Dict[str, Tuple[int, str]]):
        super().__init__()
        self.responses = responses
        self.calls: List[List[str]] = []

    def _run(
        self, args: List[str], cwd: Optional[str] = None, strip: bool = True
    ) -> Tuple[int, str, str]:
        self.calls.append(list(args))
        key = " ".join(args)
        if key in self.responses:
            code, out = self.responses[key]
            return code, out, ""
        # Longest prefix wins, so a specific pattern is never shadowed by a
        # shorter one (e.g. "diff HEAD" must not answer "diff HEAD~1 HEAD").
        matches = sorted((p for p in self.responses if key.startswith(p)), key=len, reverse=True)
        if matches:
            code, out = self.responses[matches[0]]
            return code, out, ""
        return 1, "", "no scripted response"

    def issued(self, fragment: str) -> bool:
        return any(fragment in " ".join(call) for call in self.calls)


class TestPorcelainParsing(unittest.TestCase):
    def test_plain_modification(self):
        self.assertEqual(parse_porcelain_line(" M dat/gui/app.py"), (" M", "dat/gui/app.py"))

    def test_untracked(self):
        self.assertEqual(parse_porcelain_line("?? new_file.py"), ("??", "new_file.py"))

    def test_rename_reports_the_destination(self):
        """A naive split kept "old -> new" as one filename."""
        self.assertEqual(
            parse_porcelain_line("R  old/name.py -> new/name.py"),
            ("R ", "new/name.py"),
        )

    def test_copy_reports_the_destination(self):
        self.assertEqual(parse_porcelain_line("C  a.py -> b.py"), ("C ", "b.py"))

    def test_quoted_path_is_unquoted(self):
        self.assertEqual(
            parse_porcelain_line('?? "dir/file with spaces.py"'),
            ("??", "dir/file with spaces.py"),
        )

    def test_path_containing_arrow_like_text_is_not_mangled(self):
        self.assertEqual(parse_porcelain_line(" M docs/a.py"), (" M", "docs/a.py"))

    def test_garbage_lines_are_ignored(self):
        self.assertIsNone(parse_porcelain_line(""))
        self.assertIsNone(parse_porcelain_line("??"))
        self.assertIsNone(parse_porcelain_line("?? "))


class TestWorkStatus(unittest.TestCase):
    """Which porcelain codes count as work worth documenting."""

    def test_modifications_and_additions_count(self):
        for status in ("M ", " M", "MM", "A ", "AM", "R ", "C ", "T "):
            self.assertTrue(is_work_status(status), status)

    def test_untracked_and_ignored_do_not(self):
        self.assertFalse(is_work_status("??"))
        self.assertFalse(is_work_status("!!"))

    def test_deletions_do_not_in_either_column(self):
        for status in ("D ", " D", "AD", "RD"):
            self.assertFalse(is_work_status(status), status)


class TestChangedFiles(unittest.TestCase):
    def test_untracked_files_are_not_listed_as_changes(self):
        """A scratch note or a local .env in the tree is not part of the
        change being written up - listing it put clutter straight into the
        document's "Changes Done" section."""
        git = FakeGit({
            "status --porcelain -uall": (0, " M dat/gui/app.py\n?? scratch.txt\n?? .env.local"),
        })
        self.assertEqual(git.get_changed_files(), ["dat/gui/app.py"])

    def test_deleted_files_are_not_listed_as_changes(self):
        git = FakeGit({
            "status --porcelain -uall": (0, " M kept.py\n D gone.py\nD  also_gone.py"),
        })
        self.assertEqual(git.get_changed_files(), ["kept.py"])

    def test_staged_and_unstaged_work_both_count(self):
        git = FakeGit({
            "status --porcelain -uall": (0, "A  staged_new.py\n M unstaged_edit.py\nM  staged_edit.py"),
        })
        self.assertEqual(
            git.get_changed_files(),
            ["staged_edit.py", "staged_new.py", "unstaged_edit.py"],
        )

    def test_untracked_all_is_still_requested_for_the_diff(self):
        """`get_changed_files` filters untracked files out, but the *diff* of
        a brand-new file still has to reach the summary - which needs `-uall`,
        or git collapses new files into a single directory entry."""
        git = FakeGit({
            "status --porcelain -uall": (0, "?? pkg/new_one.py\n?? pkg/new_two.py"),
        })
        self.assertEqual(git.get_untracked_files(), ["pkg/new_one.py", "pkg/new_two.py"])
        self.assertTrue(git.issued("-uall"), "without -uall git collapses new files into a directory")

    def test_renamed_file_is_listed_once_by_destination(self):
        git = FakeGit({"status --porcelain -uall": (0, "R  old.py -> new.py")})
        self.assertEqual(git.get_changed_files(), ["new.py"])

    def test_status_output_is_not_stripped(self):
        """Columns 1-2 of a porcelain line are the worktree state, so leading
        whitespace is data. Stripping the output shifted the *first* line by a
        character: ' M "My File.md"' came back as 'My File.md"' - a mangled
        name in the document, and a misread status."""
        git = FakeGit({"status --porcelain -uall": (0, ' M "My File.md"\n M second.py\n')})

        self.assertEqual(git.get_changed_files(), ["My File.md", "second.py"])

    def test_first_line_untracked_state_survives(self):
        git = FakeGit({"status --porcelain -uall": (0, " D gone.py\n?? fresh.py")})
        self.assertEqual(git.get_untracked_files(), ["fresh.py"])

    def _branch_repo(self, status: str, range_files: str):
        return FakeGit({
            "status --porcelain -uall": (0, status),
            "rev-parse --abbrev-ref HEAD": (0, "feature/X-1"),
            "rev-parse HEAD": (0, "headsha"),
            "rev-parse --verify --quiet origin/main": (0, "mainsha"),
            "merge-base HEAD origin/main": (0, "basesha"),
            "diff --name-only --diff-filter=ACMRT basesha..HEAD": (0, range_files),
        })

    def test_clean_tree_uses_the_branch_range(self):
        git = self._branch_repo(status="", range_files="a.py\nb.py")
        self.assertEqual(git.get_changed_files(), ["a.py", "b.py"])

    def test_committed_branch_work_is_kept_alongside_a_dirty_tree(self):
        """A dirty worktree used to *replace* the branch's committed work in
        the file list, so a document about a branch with four commits and one
        stray edit described only the stray edit."""
        git = self._branch_repo(status=" M in_progress.py", range_files="committed.py")
        self.assertEqual(git.get_changed_files(), ["committed.py", "in_progress.py"])

    def test_a_file_deleted_in_the_worktree_loses_to_the_deletion(self):
        """Committed on the branch, then deleted before the document is
        written: the end state is what gets documented."""
        git = self._branch_repo(status=" D committed.py", range_files="committed.py\nkept.py")
        self.assertEqual(git.get_changed_files(), ["kept.py"])

    def test_deletions_are_filtered_out_of_the_range_by_git(self):
        git = self._branch_repo(status="", range_files="a.py")
        git.get_changed_files()
        self.assertTrue(
            git.issued("--diff-filter=ACMRT"),
            "the commit range must exclude deletions too, not just the worktree",
        )

    def test_on_main_a_dirty_tree_does_not_pull_in_the_previous_commit(self):
        """With no branch point, `HEAD~1..HEAD` is somebody else's last commit
        as often as it is ours - it belongs in the document only when there is
        no uncommitted work that supersedes it."""
        git = FakeGit({
            "status --porcelain -uall": (0, " M mine.py"),
            "rev-parse --abbrev-ref HEAD": (0, "main"),
            "rev-parse HEAD": (0, "headsha"),
            "diff --name-only --diff-filter=ACMRT HEAD~1..HEAD": (0, "someone_elses.py"),
        })
        self.assertEqual(git.get_changed_files(), ["mine.py"])

    def test_on_main_a_clean_tree_still_describes_the_last_commit(self):
        git = FakeGit({
            "status --porcelain -uall": (0, ""),
            "rev-parse --abbrev-ref HEAD": (0, "main"),
            "rev-parse HEAD": (0, "headsha"),
            "diff --name-only --diff-filter=ACMRT HEAD~1..HEAD": (0, "last_commit.py"),
        })
        self.assertEqual(git.get_changed_files(), ["last_commit.py"])


class TestBaseRefAndCommits(unittest.TestCase):
    def _feature_branch_repo(self, extra=None):
        responses = {
            "rev-parse --abbrev-ref HEAD": (0, "feature/NSWM-1-thing"),
            "rev-parse HEAD": (0, "headsha"),
            "rev-parse --verify --quiet origin/main": (0, "mainsha"),
            "merge-base HEAD origin/main": (0, "basesha"),
        }
        responses.update(extra or {})
        return FakeGit(responses)

    def test_base_ref_is_the_merge_base_with_the_first_base_branch(self):
        git = self._feature_branch_repo()
        self.assertEqual(git.get_base_ref(), "basesha")

    def test_no_base_ref_when_on_the_base_branch_itself(self):
        git = FakeGit({
            "rev-parse --abbrev-ref HEAD": (0, "main"),
            "rev-parse HEAD": (0, "headsha"),
            "rev-parse --verify --quiet origin/master": (1, ""),
            "rev-parse --verify --quiet master": (1, ""),
            "rev-parse --verify --quiet origin/develop": (1, ""),
            "rev-parse --verify --quiet develop": (1, ""),
        })
        self.assertIsNone(git.get_base_ref())

    def test_merge_base_equal_to_head_is_rejected(self):
        """HEAD already merged into the base leaves nothing to diff."""
        git = FakeGit({
            "rev-parse --abbrev-ref HEAD": (0, "feature/x"),
            "rev-parse HEAD": (0, "samesha"),
            "rev-parse --verify --quiet origin/main": (0, "mainsha"),
            "merge-base HEAD origin/main": (0, "samesha"),
            "rev-parse --verify --quiet origin/master": (1, ""),
            "rev-parse --verify --quiet origin/develop": (1, ""),
            "rev-parse --verify --quiet main": (0, "mainsha"),
            "merge-base HEAD main": (0, "samesha"),
            "rev-parse --verify --quiet master": (1, ""),
            "rev-parse --verify --quiet develop": (1, ""),
        })
        self.assertIsNone(git.get_base_ref())

    def test_branch_commits_use_the_range_not_the_last_five(self):
        log = "aaaaaaaaaaa\nDev\n2026-01-01\nFirst on branch\n---END---"
        git = self._feature_branch_repo({"log": (0, log)})
        commits = git.get_branch_commits()

        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0].message, "First on branch")
        self.assertTrue(git.issued("basesha..HEAD"),
                        "commits should be scoped to this branch's range")

    def test_branch_commits_fall_back_when_there_is_no_range(self):
        log = "bbbbbbbbbbb\nDev\n2026-01-01\nSome commit\n---END---"
        git = FakeGit({
            "rev-parse --abbrev-ref HEAD": (0, "main"),
            "rev-parse HEAD": (0, "headsha"),
            "rev-parse --verify --quiet": (1, ""),
            "log": (0, log),
        })
        commits = git.get_branch_commits()
        self.assertEqual(len(commits), 1)
        self.assertTrue(git.issued("-n5"))


class TestRawDiff(unittest.TestCase):
    def test_uncommitted_changes_win(self):
        git = FakeGit({
            "diff HEAD": (0, "diff --git a/a.py b/a.py\n+change"),
            "status --porcelain -uall": (0, ""),
        })
        self.assertIn("+change", git.get_raw_diff())

    def test_branch_range_used_when_the_tree_is_clean(self):
        git = FakeGit({
            "diff HEAD": (0, ""),
            "status --porcelain -uall": (0, ""),
            "rev-parse --abbrev-ref HEAD": (0, "feature/x"),
            "rev-parse HEAD": (0, "headsha"),
            "rev-parse --verify --quiet origin/main": (0, "mainsha"),
            "merge-base HEAD origin/main": (0, "basesha"),
            "diff basesha..HEAD": (0, "diff --git a/b.py b/b.py\n+committed on branch"),
        })
        diff = git.get_raw_diff()

        self.assertIn("+committed on branch", diff)
        self.assertTrue(git.issued("diff basesha..HEAD"),
                        "a multi-commit branch must not be reduced to HEAD~1")

    def test_previous_commit_is_the_last_resort(self):
        git = FakeGit({
            "diff HEAD": (0, ""),
            "status --porcelain -uall": (0, ""),
            "rev-parse --abbrev-ref HEAD": (0, "main"),
            "rev-parse HEAD": (0, "headsha"),
            "rev-parse --verify --quiet": (1, ""),
            "diff HEAD~1 HEAD": (0, "diff --git a/c.py b/c.py\n+last commit"),
        })
        self.assertIn("+last commit", git.get_raw_diff())

    def test_no_diff_available(self):
        git = FakeGit({
            "diff HEAD": (0, ""),
            "status --porcelain -uall": (0, ""),
            "rev-parse": (1, ""),
            "diff HEAD~1 HEAD": (0, ""),
        })
        self.assertEqual(git.get_raw_diff(), "")


class TestUntrackedDiff(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="dat-git-")

    def _write(self, name: str, content: bytes) -> str:
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return name

    def test_new_file_content_becomes_a_diff(self):
        self._write("pkg/new_screen.py", b"class NewScreen:\n    pass\n")
        git = FakeGit({"status --porcelain -uall": (0, "?? pkg/new_screen.py")})

        diff = git.get_untracked_diff(cwd=self.repo)

        self.assertIn("diff --git a/pkg/new_screen.py b/pkg/new_screen.py", diff)
        self.assertIn("new file mode", diff)
        self.assertIn("--- /dev/null", diff)
        self.assertIn("+class NewScreen:", diff)
        self.assertIn("@@ -0,0 +1,2 @@", diff)

    def test_new_files_are_included_in_the_overall_diff(self):
        """git diff never shows untracked content, so this was invisible."""
        self._write("brand_new.py", b"print('hi')\n")
        git = FakeGit({
            "diff HEAD": (0, ""),
            "status --porcelain -uall": (0, "?? brand_new.py"),
        })
        self.assertIn("+print('hi')", git.get_raw_diff(cwd=self.repo))

    def test_binary_files_are_skipped(self):
        self._write("logo.png", b"\x89PNG\r\n\x1a\n\x00\x00binary")
        git = FakeGit({"status --porcelain -uall": (0, "?? logo.png")})
        self.assertEqual(git.get_untracked_diff(cwd=self.repo), "")

    def test_oversized_files_are_skipped(self):
        self._write("huge.txt", b"a" * 300_000)
        git = FakeGit({"status --porcelain -uall": (0, "?? huge.txt")})
        self.assertEqual(git.get_untracked_diff(cwd=self.repo), "")

    def test_missing_or_unreadable_file_is_skipped(self):
        git = FakeGit({"status --porcelain -uall": (0, "?? gone.py")})
        self.assertEqual(git.get_untracked_diff(cwd=self.repo), "")

    def test_tracked_modifications_are_not_duplicated_as_new_files(self):
        self._write("tracked.py", b"content\n")
        git = FakeGit({"status --porcelain -uall": (0, " M tracked.py")})
        self.assertEqual(git.get_untracked_diff(cwd=self.repo), "")

    def test_the_users_index_is_never_touched(self):
        self._write("new.py", b"x = 1\n")
        git = FakeGit({"status --porcelain -uall": (0, "?? new.py")})
        git.get_untracked_diff(cwd=self.repo)

        for call in git.calls:
            self.assertNotIn("add", call, "must not stage anything in the user's repo")


class TestSensitiveUntrackedFiles(unittest.TestCase):
    """Untracked files are read by DAT and their whole contents go into the
    AI prompt - which, with a Gemini key, leaves the machine. No reviewer ever
    approved these files, so credentials must never be among them."""

    def test_credential_files_are_refused(self):
        for name in (
            ".env", ".env.local", "prod.env",
            "local.properties", "google-services.json", "GoogleService-Info.plist",
            "serviceAccount.json", "myapp-adminsdk-abc123.json",
            "deploy.pem", "release.jks", "upload.keystore", "server.key", "cert.crt",
            "id_rsa", "id_ed25519",
            ".npmrc", ".netrc", ".pypirc", ".pgpass",
            "db_credentials.ini", "aws_secrets.yaml", "user_password.txt",
            "terraform.tfstate",
        ):
            self.assertEqual(
                untracked_skip_reason(name),
                "looks like a credential or local configuration",
                f"{name} must never be read",
            )

    def test_case_and_directory_do_not_defeat_the_check(self):
        """The same file is `.ENV` on one machine and `.env` on another, and
        it is just as sensitive three directories down."""
        self.assertIsNotNone(untracked_skip_reason(".ENV.Production"))
        self.assertIsNotNone(untracked_skip_reason("app/config/local.properties"))
        self.assertIsNotNone(untracked_skip_reason("app\\config\\deploy.PEM"))

    def test_generated_and_editor_files_are_refused_as_noise(self):
        for name in ("debug.log", "bundle.min.js", "app.js.map", "package-lock.json",
                     "yarn.lock", "notes.py.bak", ".DS_Store"):
            self.assertEqual(
                untracked_skip_reason(name),
                "generated or editor file, not reviewable source",
                name,
            )

    def test_real_source_files_are_still_read(self):
        """The filter must not cost DAT the thing it exists for: a brand-new
        screen or class reaching the summary."""
        for name in ("new_screen.py", "SyncService.kt", "Widget.vue", "main.dart",
                     "api/routes.ts", "styles.scss", "Dockerfile", "README.md",
                     "schema.sql", "CMakeLists.txt"):
            self.assertIsNone(untracked_skip_reason(name), name)

    def test_extra_patterns_come_from_the_environment(self):
        with mock.patch.dict(os.environ, {"DAT_UNTRACKED_EXCLUDE": "fixtures/*.json, *.internal"}):
            self.assertEqual(
                untracked_skip_reason("fixtures/big.json"),
                "excluded by $DAT_UNTRACKED_EXCLUDE",
            )
            self.assertEqual(
                untracked_skip_reason("notes.internal"),
                "excluded by $DAT_UNTRACKED_EXCLUDE",
            )
            self.assertIsNone(untracked_skip_reason("src/app.json"))

    def test_an_empty_environment_variable_excludes_nothing(self):
        with mock.patch.dict(os.environ, {"DAT_UNTRACKED_EXCLUDE": " , "}):
            self.assertIsNone(untracked_skip_reason("app.py"))


class TestSensitiveContentNeverReachesTheDiff(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="dat-leak-")

    def _write(self, name: str, content: bytes) -> None:
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)

    def _diff(self, status: str) -> str:
        git = FakeGit({"status --porcelain -uall": (0, status), "diff HEAD": (0, "")})
        with contextlib.redirect_stderr(io.StringIO()):
            return git.get_raw_diff(cwd=self.repo)

    def test_api_key_in_an_untracked_env_file_is_not_in_the_prompt(self):
        self._write(".env.local", b"GEMINI_KEY=AIzaSyREAL_SECRET\n")
        self._write("new_screen.py", b"class NewScreen:\n    pass\n")

        diff = self._diff("?? .env.local\n?? new_screen.py")

        self.assertNotIn("AIzaSyREAL_SECRET", diff)
        self.assertNotIn(".env.local", diff)
        self.assertIn("+class NewScreen:", diff, "real new source must survive the filter")

    def test_signing_password_in_local_properties_is_not_in_the_prompt(self):
        self._write("local.properties", b"sdk.dir=/opt/android\nSIGNING_PASS=hunter2\n")
        self.assertNotIn("hunter2", self._diff("?? local.properties"))

    def test_private_key_is_not_in_the_prompt(self):
        self._write("deploy.pem", b"-----BEGIN RSA PRIVATE KEY-----\nMIIEow==\n")
        self.assertNotIn("PRIVATE KEY", self._diff("?? deploy.pem"))

    def test_skipped_files_are_reported_on_stderr_not_stdout(self):
        """A silent drop is the one thing this filter must not do - and stdout
        carries the MCP server's JSON-RPC stream, so the notice cannot go there."""
        self._write(".env", b"KEY=v\n")
        git = FakeGit({"status --porcelain -uall": (0, "?? .env")})

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            git.get_untracked_diff(cwd=self.repo)

        self.assertEqual(out.getvalue(), "", "stdout must stay pure for JSON-RPC")
        self.assertIn(".env", err.getvalue())
        self.assertIn("credential", err.getvalue())
        self.assertIn("git add", err.getvalue(), "the notice must say how to override it")

    def test_nothing_is_reported_when_nothing_was_skipped(self):
        self._write("app.py", b"x = 1\n")
        git = FakeGit({"status --porcelain -uall": (0, "?? app.py")})

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            git.get_untracked_diff(cwd=self.repo)

        self.assertEqual(err.getvalue(), "")

    def test_staging_a_file_is_the_deliberate_way_to_include_it(self):
        """The escape hatch: staged content reaches the AI through
        `git diff HEAD`, so sharing it is an explicit act."""
        self._write("local.properties", b"SIGNING_PASS=hunter2\n")
        git = FakeGit({
            "status --porcelain -uall": (0, "A  local.properties"),
            "diff HEAD": (0, "diff --git a/local.properties b/local.properties\n+SIGNING_PASS=hunter2"),
        })
        self.assertIn("hunter2", git.get_raw_diff(cwd=self.repo))


if __name__ == "__main__":
    unittest.main()
