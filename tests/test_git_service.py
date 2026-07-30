import unittest
from dat.services.git_service import GitService

class TestGitService(unittest.TestCase):
    def test_parse_branch_name_feature_with_ticket(self):
        service = GitService()
        title, ticket = service.parse_branch_name("feature/JIRA-1042-user-auth-flow")
        self.assertEqual(ticket, "JIRA-1042")
        self.assertIn("User Auth Flow", title)

    def test_parse_branch_name_bugfix_no_ticket(self):
        service = GitService()
        title, ticket = service.parse_branch_name("bugfix/fix-login-button-spacing")
        self.assertIsNone(ticket)
        self.assertEqual(title, "Fix Login Button Spacing")

    def test_parse_branch_name_plain_branch(self):
        service = GitService()
        title, ticket = service.parse_branch_name("main")
        self.assertIsNone(ticket)
        self.assertEqual(title, "Main")

if __name__ == "__main__":
    unittest.main()
