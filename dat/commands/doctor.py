from typing import Dict, Any
from dat.commands.base import BaseCommand
from dat.utils.exit_codes import ExitCode

class DoctorCommand(BaseCommand):
    def execute(self, args: Dict[str, Any]) -> ExitCode:
        print("\n=== Developer Automation Toolkit (DAT_CLI) Environment Doctor ===\n")
        
        is_git = self.container.git_adapter.is_git_repo()
        print(f"  [1] Git Binary & Repository : {'OK (Inside repo)' if is_git else 'Warning (Not inside git repo)'}")

        try:
            import docx
            docx_ver = getattr(docx, '__version__', 'Installed')
            print(f"  [2] python-docx             : OK ({docx_ver})")
        except ImportError:
            print(f"  [2] python-docx             : MISSING")

        try:
            import yaml
            print(f"  [3] PyYAML                  : OK")
        except ImportError:
            print(f"  [3] PyYAML                  : MISSING")

        try:
            import tkinter
            print(f"  [4] Tkinter (GUI)           : OK")
        except ImportError:
            print(f"  [4] Tkinter (GUI)           : MISSING (Linux: sudo apt install python3-tk)")

        try:
            import customtkinter
            print(f"  [5] customtkinter (GUI)     : OK")
        except ImportError:
            print(f"  [5] customtkinter (GUI)     : MISSING (pip install customtkinter)")

        try:
            import tkinterdnd2
            print(f"  [6] tkinterdnd2 (drag&drop) : OK")
        except ImportError:
            print(f"  [6] tkinterdnd2 (drag&drop) : Not installed (GUI falls back to Browse-button only)")

        print(f"  [7] Configuration Path      : {self.container.configuration_service.config_file}")
        print("\nDiagnostics complete.\n")
        return ExitCode.SUCCESS
