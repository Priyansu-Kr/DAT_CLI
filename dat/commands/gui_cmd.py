from typing import Any, Dict
from dat.commands.base import BaseCommand
from dat.commands.doctor import tkinter_install_hint
from dat.utils.exit_codes import ExitCode


class GuiCommand(BaseCommand):
    def execute(self, args: Dict[str, Any]) -> ExitCode:
        try:
            import tkinter  # noqa: F401
        except ImportError:
            print(
                "The DAT GUI requires Tkinter, which pip cannot install - it comes "
                "from your Python/OS installation:\n"
                f"  {tkinter_install_hint()}"
            )
            return ExitCode.VALIDATION_ERROR

        from dat.gui import macos_compat
        macos_compat.apply()

        try:
            import customtkinter  # noqa: F401
        except ImportError:
            print(
                "The DAT GUI requires the 'customtkinter' package (and optionally "
                "'tkinterdnd2' for drag-and-drop). Install with:\n"
                "  pip install customtkinter tkinterdnd2"
            )
            return ExitCode.VALIDATION_ERROR
        except Exception as e:
            print(f"[Error] customtkinter failed to load: {e}")
            return ExitCode.UNEXPECTED_ERROR

        from dat.gui.app import DATGuiApp

        try:
            app = DATGuiApp(container=self.container)
            app.run()
        except Exception as e:
            print(f"[Error] DAT GUI failed to start: {e}")
            return ExitCode.UNEXPECTED_ERROR

        return ExitCode.SUCCESS
