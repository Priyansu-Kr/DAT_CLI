import unittest
from unittest import mock

from dat.cli.args import parse_args
from dat.commands.generate_doc import GenerateDocCommand
from dat.utils.exit_codes import ExitCode

class TestCLIArgs(unittest.TestCase):
    def test_generate_doc_default_args(self):
        args = parse_args(["generate-doc"])
        self.assertEqual(args.command, "generate-doc")
        # No hardcoded default - DocumentService derives the output filename
        # from the (possibly git-inferred) title when this is None.
        self.assertIsNone(args.output)
        self.assertEqual(args.format, "docx")

    def test_generate_doc_custom_args(self):
        args = parse_args([
            "generate-doc",
            "--title", "My Feature",
            "--ticket", "JIRA-999",
            "--output", "custom.docx",
            "--author", "DevUser"
        ])
        self.assertEqual(args.title, "My Feature")
        self.assertEqual(args.ticket, "JIRA-999")
        self.assertEqual(args.output, "custom.docx")
        self.assertEqual(args.author, "DevUser")

    def test_generate_doc_with_images(self):
        args = parse_args([
            "generate-doc",
            "--images", "screen1.png", "screen2.png"
        ])
        self.assertEqual(args.images, ["screen1.png", "screen2.png"])

    def test_generate_doc_seed_file_defaults_to_none(self):
        args = parse_args(["generate-doc"])
        self.assertIsNone(args.seed_file)

    def test_generate_doc_seed_file_arg(self):
        args = parse_args(["generate-doc", "--seed-file", "/tmp/seed.json"])
        self.assertEqual(args.seed_file, "/tmp/seed.json")

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

    def test_headless_defaults_to_off(self):
        self.assertFalse(parse_args(["generate-doc"]).headless)

    def test_headless_flag(self):
        self.assertTrue(parse_args(["generate-doc", "--headless"]).headless)


class TestGenerateDocDestination(unittest.TestCase):
    """A generated document goes to the Preview Panel unless --headless."""

    def setUp(self):
        self.container = mock.Mock()
        self.container.config = mock.Mock(ai_api_key="k" * 40, author_name="Dev")
        self.command = GenerateDocCommand(self.container)

    def _run(self, args):
        with mock.patch.object(GenerateDocCommand, "_launch_gui_preview",
                               return_value=ExitCode.SUCCESS) as preview:
            code = self.command.execute(args)
        return code, preview

    def test_plain_generate_doc_opens_the_preview_panel(self):
        """The reported bug: 'dat generate-doc' quietly writing a file."""
        code, preview = self._run({})

        self.assertEqual(code, ExitCode.SUCCESS)
        self.assertTrue(preview.called, "the panel must open by default")
        self.assertFalse(self.container.document_service.generate_documentation.called)

    def test_output_path_and_format_still_open_the_panel(self):
        _code, preview = self._run({"output": "/tmp/x.md", "format": "md"})
        self.assertTrue(preview.called)
        self.assertFalse(self.container.document_service.generate_documentation.called)

    def test_select_images_still_opens_the_panel(self):
        _code, preview = self._run({"select_images": True})
        self.assertTrue(preview.called)

    def test_headless_writes_the_file_without_the_panel(self):
        self.container.document_service.generate_documentation.return_value = "/tmp/out.docx"
        code, preview = self._run({"headless": True, "output": "/tmp/out.docx"})

        self.assertEqual(code, ExitCode.SUCCESS)
        self.assertFalse(preview.called)
        self.assertTrue(self.container.document_service.generate_documentation.called)

    def test_seed_file_always_opens_the_panel_even_with_headless(self):
        """A seed file carries content that only the panel can show."""
        with mock.patch.object(GenerateDocCommand, "_load_seed_file", return_value=(None, {})):
            _code, preview = self._run({"headless": True, "seed_file": "/tmp/seed.json"})
        self.assertTrue(preview.called)
        self.assertFalse(self.container.document_service.generate_documentation.called)


class TestGraphicalSessionDetection(unittest.TestCase):
    def test_desktop_platforms_always_have_a_session(self):
        for platform in ("darwin", "win32"):
            with mock.patch("dat.commands.generate_doc.sys.platform", platform):
                self.assertTrue(GenerateDocCommand._graphical_session_available())

    def test_linux_needs_a_display(self):
        with mock.patch("dat.commands.generate_doc.sys.platform", "linux"):
            with mock.patch.dict("os.environ", {"DISPLAY": ":0"}, clear=True):
                self.assertTrue(GenerateDocCommand._graphical_session_available())
            with mock.patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=True):
                self.assertTrue(GenerateDocCommand._graphical_session_available())
            with mock.patch.dict("os.environ", {}, clear=True):
                self.assertFalse(GenerateDocCommand._graphical_session_available())

    def test_headless_box_explains_the_flag_instead_of_crashing(self):
        console = mock.Mock()
        command = GenerateDocCommand(mock.Mock())
        with mock.patch.object(GenerateDocCommand, "_graphical_session_available", return_value=False):
            code = command._launch_gui_preview(console, None, None, "Dev", "", [], None)

        self.assertEqual(code, ExitCode.VALIDATION_ERROR)
        printed = " ".join(str(call) for call in console.print.call_args_list)
        self.assertIn("--headless", printed)
        self.assertIn("No graphical session", printed)


if __name__ == "__main__":
    unittest.main()
