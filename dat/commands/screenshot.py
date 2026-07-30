import sys
from typing import Dict, Any
from dat.commands.base import BaseCommand
from dat.utils.exit_codes import ExitCode

class ScreenshotCommand(BaseCommand):
    def execute(self, args: Dict[str, Any]) -> ExitCode:
        output_path = args.get("output", "screenshot.png")
        device_id = args.get("device")

        try:
            shot_info = self.container.screenshot_service.capture_adb_screenshot(
                output_path=output_path,
                device_id=device_id
            )
            print(f"\n[SUCCESS] Screenshot captured -> {shot_info.file_path}")
            return ExitCode.SUCCESS
        except Exception as e:
            print(f"\n[ERROR] Screenshot capture failed: {e}", file=sys.stderr)
            return ExitCode.EXTERNAL_TOOL_ERROR
