import unittest
from dat.services.git_service import GitService


class _RaisingGitAdapter:
    def is_git_repo(self, cwd=None):
        raise RuntimeError("simulated git failure (e.g. missing binary)")


class TestGitService(unittest.TestCase):
    def test_parse_branch_name_feature_with_ticket(self):
        service = GitService()
        # No action verb is present, so "user"/"auth" are heuristically
        # treated as an author-name prefix (matching the "TICKET-Author-Name-
        # verb-topic" convention this heuristic targets) and only "flow"
        # remains as the topic.
        title, ticket, author = service.parse_branch_name("feature/JIRA-1042-user-auth-flow")
        self.assertEqual(ticket, "JIRA-1042")
        self.assertIn("Flow", title)
        self.assertEqual(author, "User Auth")

    def test_parse_branch_name_bugfix_no_ticket(self):
        service = GitService()
        title, ticket, author = service.parse_branch_name("bugfix/fix-login-button-spacing")
        self.assertIsNone(ticket)
        self.assertEqual(title, "Fix Login Button Spacing")

    def test_parse_branch_name_plain_branch(self):
        service = GitService()
        title, ticket, author = service.parse_branch_name("main")
        self.assertIsNone(ticket)
        self.assertEqual(title, "Main")
        self.assertIsNone(author)

    def test_get_git_info_never_raises_and_returns_defaults_on_failure(self):
        service = GitService(git_adapter=_RaisingGitAdapter())
        git_info = service.get_git_info()
        self.assertEqual(git_info.branch_name, "standalone-repo")
        self.assertIsNotNone(git_info.inferred_title)
        self.assertEqual(git_info.changed_files, [])

if __name__ == "__main__":
    unittest.main()
