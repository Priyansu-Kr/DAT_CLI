"""Decoupled state + preview-building logic for the DAT GUI.

Nothing in this module imports tkinter/customtkinter, so the reactive
preview logic can be exercised in unit tests without a display.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from dat.models.doc_request import ChangeSummary, DEFAULT_SECTIONS
from dat.models.git_info import GitInfo
from dat.models.screenshot_info import ScreenshotInfo
from dat.renderers.screenshot_grouping import group_screenshots_by_test_case

TOGGLE_ORDER: List[str] = [
    "header",
    "metadata_table",
    "changes_done",
    "test_cases_table",
    "screenshots",
]

TOGGLE_LABELS: Dict[str, str] = {
    "header": "Header",
    "metadata_table": "Metadata Table",
    "changes_done": "Changes Done",
    "test_cases_table": "Test Cases Table",
    "screenshots": "Screenshots",
}


@dataclass
class GuiState:
    ticket_id: str = ""
    topic: str = ""
    author: str = "Developer"
    approved_by: str = ""
    toggles: Dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_SECTIONS))
    screenshots: List[ScreenshotInfo] = field(default_factory=list)
    summary: ChangeSummary = field(default_factory=lambda: ChangeSummary(overview=""))
    summary_user_edited: bool = False
    git_info: Optional[GitInfo] = None

    @property
    def title(self) -> str:
        parts = [p for p in (self.ticket_id.strip(), self.topic.strip()) if p]
        return " ".join(parts) if parts else "Untitled Feature"

    @property
    def has_summary_content(self) -> bool:
        return bool(
            self.summary.overview
            or self.summary.key_points
            or self.summary.impact_areas
            or self.summary.test_cases
        )

    def set_toggle(self, key: str, value: bool) -> None:
        self.toggles[key] = bool(value)

    def add_screenshot(self, shot: ScreenshotInfo) -> None:
        self.screenshots.append(shot)

    def remove_screenshot(self, file_path: str) -> None:
        self.screenshots = [s for s in self.screenshots if s.file_path != file_path]

    def reorder_screenshots(self, new_order_paths: List[str]) -> None:
        by_path = {s.file_path: s for s in self.screenshots}
        self.screenshots = [by_path[p] for p in new_order_paths if p in by_path]

    def set_screenshot_test_case(self, file_path: str, index: Optional[int]) -> None:
        for s in self.screenshots:
            if s.file_path == file_path:
                s.test_case_index = index
                break

    def set_approved_by(self, value: str) -> None:
        self.approved_by = value

    # --- Editable AI-generated content ---------------------------------

    def set_impact_areas_text(self, text: str) -> None:
        self.summary.impact_areas = [t.strip() for t in text.split(",") if t.strip()]
        self.summary_user_edited = True

    def set_key_points(self, points: List[str]) -> None:
        self.summary.key_points = [p for p in points if p.strip()]
        self.summary_user_edited = True

    def set_test_cases(self, cases: List[str]) -> None:
        self.summary.test_cases = [c for c in cases if c.strip()]
        self.summary_user_edited = True
        # Screenshots assigned to a test case that no longer exists fall back to Auto.
        valid_count = len(self.summary.test_cases)
        for s in self.screenshots:
            if s.test_case_index is not None and s.test_case_index >= valid_count:
                s.test_case_index = None

    @classmethod
    def from_git_info(cls, git_info: GitInfo, author: Optional[str] = None) -> "GuiState":
        ticket_id = git_info.ticket_id or ""
        topic = git_info.inferred_title or ""
        if ticket_id and topic.upper().startswith(ticket_id.upper()):
            topic = topic[len(ticket_id):].strip()
        return cls(
            ticket_id=ticket_id,
            topic=topic,
            author=author or git_info.author_name or "Developer",
            git_info=git_info,
        )


@dataclass
class PreviewBlock:
    """A single renderable unit of the virtual document preview."""
    kind: str
    heading: Optional[str] = None
    text: Optional[str] = None
    bullets: List[str] = field(default_factory=list)
    table_headers: List[str] = field(default_factory=list)
    table_rows: List[List[str]] = field(default_factory=list)
    screenshot_groups: List[tuple] = field(default_factory=list)


def build_preview_content(state: GuiState) -> List[PreviewBlock]:
    """Build a framework-agnostic model of the live preview from GuiState.

    Mirrors the section structure produced by DocxRenderer so the preview
    stays a faithful representation of the exported .docx file.
    """
    blocks: List[PreviewBlock] = []
    toggles = state.toggles
    summary = state.summary

    if toggles.get("header", True):
        blocks.append(PreviewBlock(kind="title", text=state.title))

    if toggles.get("metadata_table", True):
        blocks.append(PreviewBlock(
            kind="metadata_table",
            heading="Task Detail",
            table_rows=[
                ["Ticket No.", state.ticket_id or ""],
                ["Short Description", state.topic or ""],
                ["Document Date", datetime.now().strftime("%d-%B-%Y")],
                ["Created By", state.author or ""],
                ["Approved By", state.approved_by or ""],
            ],
        ))

    if toggles.get("changes_done", True):
        if state.has_summary_content:
            modules_text = ", ".join(summary.impact_areas) if summary.impact_areas else "Main Module"
            bullets = list(summary.key_points)
        else:
            modules_text = "Main Module"
            bullets = ["Implemented core logic changes."]
        blocks.append(PreviewBlock(
            kind="changes_done",
            heading="Changes Done",
            text=f"Affected Module: {modules_text}",
            bullets=bullets,
        ))

    if toggles.get("test_cases_table", True) and summary.test_cases:
        rows = [[f"{i + 1}.", case, "Success"] for i, case in enumerate(summary.test_cases)]
        blocks.append(PreviewBlock(
            kind="test_cases_table",
            heading="Test Cases",
            table_headers=["Index", "Case", "Status"],
            table_rows=rows,
        ))

    if toggles.get("screenshots", True) and state.screenshots:
        groups = group_screenshots_by_test_case(state.screenshots, summary.test_cases)
        blocks.append(PreviewBlock(
            kind="screenshots",
            heading="Screenshots",
            screenshot_groups=groups,
        ))

    return blocks
