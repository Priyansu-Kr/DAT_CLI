from typing import Dict, Any
from dat.commands.base import BaseCommand
from dat.utils.exit_codes import ExitCode

class DoctorCommand(BaseCommand):
    def execute(self, args: Dict[str, Any]) -> ExitCode:
        print("\n=== Developer Automation Toolkit (DAT_CLI) Environment Doctor ===\n")
        
        is_git = self.container.git_adapter.is_git_repo()
        print(f"  [1] Git Binary & Repository : {'OK (Inside repo)' if is_git else 'Warning (Not inside git repo)'}")

        adb_avail = self.container.adb_adapter.is_adb_available()
        devices = self.container.adb_adapter.get_devices() if adb_avail else []
        print(f"  [2] ADB Available           : {'OK' if adb_avail else 'Not Found (Android features limited)'}")
        print(f"      Connected ADB Devices   : {len(devices)} device(s) ({', '.join(devices) if devices else 'None'})")

        try:
            import docx
            docx_ver = getattr(docx, '__version__', 'Installed')
            print(f"  [3] python-docx             : OK ({docx_ver})")
        except ImportError:
            print(f"  [3] python-docx             : MISSING")

        try:
            import yaml
            print(f"  [4] PyYAML                  : OK")
        except ImportError:
            print(f"  [4] PyYAML                  : MISSING")

        try:
            import tkinter
            print(f"  [5] Tkinter (GUI)           : OK")
        except ImportError:
            print(f"  [5] Tkinter (GUI)           : MISSING (Linux: sudo apt install python3-tk)")

        try:
            import customtkinter
            print(f"  [6] customtkinter (GUI)     : OK")
        except ImportError:
            print(f"  [6] customtkinter (GUI)     : MISSING (pip install customtkinter)")

        try:
            import tkinterdnd2
            print(f"  [7] tkinterdnd2 (drag&drop) : OK")
        except ImportError:
            print(f"  [7] tkinterdnd2 (drag&drop) : Not installed (GUI falls back to Browse-button only)")

        print(f"  [8] Configuration Path      : {self.container.configuration_service.config_file}")
        print("\nDiagnostics complete.\n")
        return ExitCode.SUCCESS
