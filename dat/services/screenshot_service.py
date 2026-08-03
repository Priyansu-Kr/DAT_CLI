import os
from typing import List, Optional
from dat.adapters.filesystem_adapter import FilesystemAdapter
from dat.models.screenshot_info import ScreenshotInfo

class ScreenshotService:
    def __init__(self, fs_adapter: Optional[FilesystemAdapter] = None):
        self.fs_adapter = fs_adapter or FilesystemAdapter()

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
