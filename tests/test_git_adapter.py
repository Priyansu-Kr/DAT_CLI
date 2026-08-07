"""How DAT decides what code is under review.

The adapter is driven through a fake `_run`, so these assert the exact git
commands issued and how their output is interpreted - no real repository or
network required.
"""
import os
import tempfile
import unittest
from typing import Dict, List, Optional, Tuple

from dat.adapters.git_adapter import GitAdapter, parse_porcelain_line


class FakeGit(GitAdapter):
    """GitAdapter with `_run` replaced by a scripted responder."""

    def __init__(self, responses: Dict[str, Tuple[int, str]]):
        super().__init__()
        self.responses = responses
        self.calls: List[List[str]] = []

    def _run(self, args: List[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
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


class TestChangedFiles(unittest.TestCase):
    def test_uses_untracked_all_so_new_files_are_listed_individually(self):
        git = FakeGit({
            "status --porcelain -uall": (0, " M dat/gui/app.py\n?? pkg/new_one.py\n?? pkg/new_two.py"),
        })
        files = git.get_changed_files()

        self.assertEqual(files, ["dat/gui/app.py", "pkg/new_one.py", "pkg/new_two.py"])
        self.assertTrue(git.issued("-uall"), "without -uall git collapses new files into a directory")

    def test_renamed_file_is_listed_once_by_destination(self):
        git = FakeGit({"status --porcelain -uall": (0, "R  old.py -> new.py")})
        self.assertEqual(git.get_changed_files(), ["new.py"])

    def test_clean_tree_falls_back_to_the_branch_range(self):
        git = FakeGit({
            "status --porcelain -uall": (0, ""),
            "rev-parse --abbrev-ref HEAD": (0, "feature/X-1"),
            "rev-parse HEAD": (0, "headsha"),
            "rev-parse --verify --quiet origin/main": (0, "mainsha"),
            "merge-base HEAD origin/main": (0, "basesha"),
            "diff --name-only basesha..HEAD": (0, "a.py\nb.py"),
        })
        self.assertEqual(git.get_changed_files(), ["a.py", "b.py"])


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


if __name__ == "__main__":
    unittest.main()
