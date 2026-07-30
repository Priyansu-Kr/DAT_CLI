import unittest
from dat.cli.args import parse_args

class TestCLIArgs(unittest.TestCase):
    def test_generate_doc_default_args(self):
        args = parse_args(["generate-doc"])
        self.assertEqual(args.command, "generate-doc")
        self.assertEqual(args.output, "doc_output.docx")
        self.assertEqual(args.format, "docx")
        self.assertFalse(args.adb)

    def test_generate_doc_custom_args(self):
        args = parse_args([
            "generate-doc",
            "--title", "My Feature",
            "--ticket", "JIRA-999",
            "--output", "custom.docx",
            "--adb",
            "--author", "DevUser"
        ])
        self.assertEqual(args.title, "My Feature")
        self.assertEqual(args.ticket, "JIRA-999")
        self.assertEqual(args.output, "custom.docx")
        self.assertTrue(args.adb)
        self.assertEqual(args.author, "DevUser")

    def test_generate_doc_with_images(self):
        args = parse_args([
            "generate-doc",
            "--images", "screen1.png", "screen2.png"
        ])
        self.assertEqual(args.images, ["screen1.png", "screen2.png"])

    def test_screenshot_command(self):
        args = parse_args(["screenshot", "--output", "snap.png"])
        self.assertEqual(args.command, "screenshot")
        self.assertEqual(args.output, "snap.png")

    def test_doctor_command(self):
        args = parse_args(["doctor"])
        self.assertEqual(args.command, "doctor")

    def test_config_command(self):
        args = parse_args(["config", "init"])
        self.assertEqual(args.command, "config")
        self.assertEqual(args.action, "init")

    def test_no_command(self):
        args = parse_args([])
        self.assertIsNone(args.command)

if __name__ == "__main__":
    unittest.main()
