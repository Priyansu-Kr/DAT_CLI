from typing import Any, Dict
from dat.commands.base import BaseCommand
from dat.utils.exit_codes import ExitCode


class GuiCommand(BaseCommand):
    def execute(self, args: Dict[str, Any]) -> ExitCode:
        try:
            import tkinter  # noqa: F401
        except ImportError:
            print(
                "The DAT GUI requires Tkinter, which is a separate OS package on "
                "most Linux distributions (pip cannot install it). Install it with:\n"
                "  Debian/Ubuntu : sudo apt install python3-tk\n"
                "  Fedora/RHEL   : sudo dnf install python3-tkinter\n"
                "  Arch          : sudo pacman -S tk\n"
                "On Windows/macOS, Tkinter ships with the standard python.org installer."
            )
            return ExitCode.VALIDATION_ERROR

        try:
            import customtkinter  # noqa: F401
        except ImportError:
            print(
                "The DAT GUI requires the 'customtkinter' package (and optionally "
                "'tkinterdnd2' for drag-and-drop). Install with:\n"
                "  pip install customtkinter tkinterdnd2"
            )
            return ExitCode.VALIDATION_ERROR

        from dat.gui.app import DATGuiApp

        try:
            app = DATGuiApp(container=self.container)
            app.run()
        except Exception as e:
            print(f"[Error] DAT GUI failed to start: {e}")
            return ExitCode.UNEXPECTED_ERROR

        return ExitCode.SUCCESS
