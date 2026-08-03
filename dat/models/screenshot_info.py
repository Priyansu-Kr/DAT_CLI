from dataclasses import dataclass
from typing import Optional

@dataclass
class ScreenshotInfo:
    file_path: str
    caption: str = ""
    source: str = "local"
    width: Optional[int] = None
    height: Optional[int] = None
    test_case_index: Optional[int] = None  # None = auto-distribute / unassigned
