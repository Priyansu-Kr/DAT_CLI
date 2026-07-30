import os
import tempfile
from typing import List, Optional
from dat.adapters.adb_adapter import ADBAdapter
from dat.adapters.filesystem_adapter import FilesystemAdapter
from dat.models.screenshot_info import ScreenshotInfo

class ScreenshotService:
    def __init__(self, adb_adapter: Optional[ADBAdapter] = None, fs_adapter: Optional[FilesystemAdapter] = None):
        self.adb_adapter = adb_adapter or ADBAdapter()
        self.fs_adapter = fs_adapter or FilesystemAdapter()

    def capture_adb_screenshot(self, output_path: Optional[str] = None, device_id: Optional[str] = None) -> ScreenshotInfo:
        if not output_path:
            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, f"dat_screenshot_{os.getpid()}.png")

        success, message = self.adb_adapter.capture_screenshot(output_path, device_id=device_id)
        if not success:
            raise RuntimeError(message)

        return ScreenshotInfo(
            file_path=output_path,
            caption="Android Device Screenshot (Captured via ADB)",
            source="adb"
        )

    def process_local_images(self, paths: List[str]) -> List[ScreenshotInfo]:
        screenshots = []
        for idx, path in enumerate(paths, 1):
            abs_path = os.path.abspath(path)
            if self.fs_adapter.exists(abs_path) and self.fs_adapter.is_file(abs_path):
                filename = os.path.basename(abs_path)
                screenshots.append(ScreenshotInfo(
                    file_path=abs_path,
                    caption=f"Product Screenshot: {filename}",
                    source="local"
                ))
        return screenshots
