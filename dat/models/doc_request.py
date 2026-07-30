from dataclasses import dataclass, field
from typing import List, Optional
from dat.models.git_info import GitInfo
from dat.models.screenshot_info import ScreenshotInfo

@dataclass
class ChangeSummary:
    overview: str
    key_points: List[str] = field(default_factory=list)
    impact_areas: List[str] = field(default_factory=list)
    test_recommendations: List[str] = field(default_factory=list)
    test_cases: List[str] = field(default_factory=list)

@dataclass
class DocRequest:
    title: str
    subtitle: Optional[str] = None
    author: str = "Developer"
    ticket_id: Optional[str] = None
    git_info: Optional[GitInfo] = None
    summary: Optional[ChangeSummary] = None
    screenshots: List[ScreenshotInfo] = field(default_factory=list)
    output_format: str = "docx"
    output_path: str = "doc_output.docx"
