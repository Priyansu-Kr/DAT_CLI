"""Decoupled state + preview-building logic for the DAT GUI.

Nothing in this module imports tkinter/customtkinter, so the reactive
preview logic can be exercised in unit tests without a display.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from dat.models.doc_request import ChangeSummary, DEFAULT_SECTIONS
from dat.models.git_info import GitInfo
from dat.models.screenshot_info import ScreenshotInfo
from dat.models.template_model import (
    BLOCK_BULLET_LIST,
    BLOCK_CODE,
    BLOCK_HEADING,
    BLOCK_IMAGE,
    BLOCK_PARAGRAPH,
    BLOCK_SCREENSHOTS,
    BLOCK_SEPARATOR,
    BLOCK_SUBHEADING,
    BLOCK_TABLE,
    BLOCK_TWO_COLUMNS,
    DocumentTemplate,
    TemplateBlock,
    TemplateContext,
)
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
    # When set, the document is described by the user's custom template
    # instead of the built-in section layout.
    active_template: Optional[DocumentTemplate] = None
    # Runtime show/hide per template section, keyed by section_id. Kept
    # separate from TemplateSection.enabled (the saved default) so toggling
    # a section in the main window never rewrites the template file.
    template_toggles: Dict[str, bool] = field(default_factory=dict)

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

    # --- Custom template ------------------------------------------------

    @property
    def uses_custom_template(self) -> bool:
        return self.active_template is not None

    def set_active_template(self, template: Optional[DocumentTemplate]) -> None:
        """Switch the document to ``template`` (None = built-in layout).

        Toggle state is re-seeded from the template's saved defaults, but any
        section the user is already toggling and that still exists keeps its
        current visibility so re-saving from the builder isn't disruptive.
        """
        previous = dict(self.template_toggles)
        self.active_template = template
        if template is None:
            self.template_toggles = {}
            return
        self.template_toggles = {
            s.section_id: previous.get(s.section_id, s.enabled) for s in template.sections
        }

    def set_template_toggle(self, section_id: str, value: bool) -> None:
        self.template_toggles[section_id] = bool(value)

    def template_context(self) -> TemplateContext:
        """Live values for ``{{token}}`` substitution inside template text."""
        return TemplateContext(
            title=self.title,
            ticket_id=self.ticket_id,
            topic=self.topic,
            author=self.author,
            approved_by=self.approved_by,
            branch=getattr(self.git_info, "branch_name", "") or "",
            key_points=list(self.summary.key_points),
            impact_areas=list(self.summary.impact_areas),
            test_cases=list(self.summary.test_cases),
        )

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
    # Custom-template extras
    level: int = 2
    ordered: bool = False
    image_path: Optional[str] = None
    columns: List[str] = field(default_factory=list)
    # Relative column widths for table blocks; empty means "share evenly".
    col_weights: List[int] = field(default_factory=list)


def structure_toggle_items(state: GuiState) -> List[Tuple[str, str, bool]]:
    """(key, label, value) rows for the left panel's Document Structure list.

    Returns the built-in sections normally, or one row per section of the
    active custom template - so hide/show works identically either way.
    """
    if state.active_template is not None:
        return [
            (s.section_id, s.title or "Untitled Section", state.template_toggles.get(s.section_id, s.enabled))
            for s in state.active_template.sections
        ]
    return [(key, TOGGLE_LABELS[key], state.toggles.get(key, True)) for key in TOGGLE_ORDER]


def build_preview_content(state: GuiState) -> List[PreviewBlock]:
    """Build a framework-agnostic model of the live preview from GuiState.

    Mirrors the section structure produced by the active renderer so the
    preview stays a faithful representation of the exported .docx file.
    """
    if state.active_template is not None:
        return build_template_preview_content(state)

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


# --- Custom template preview --------------------------------------------

def build_template_preview_content(state: GuiState) -> List[PreviewBlock]:
    """Preview blocks for the custom template active in ``state``."""
    if state.active_template is None:
        return []
    return build_template_blocks(
        state.active_template,
        state.template_context(),
        screenshots=state.screenshots,
        section_overrides=state.template_toggles,
    )


def build_template_blocks(
    template: DocumentTemplate,
    context: TemplateContext,
    screenshots: Optional[List[ScreenshotInfo]] = None,
    section_overrides: Optional[Dict[str, bool]] = None,
) -> List[PreviewBlock]:
    """Map a custom template to preview blocks.

    Only visible sections contribute and `{{token}}` placeholders are
    resolved against ``context``. The mapping is intentionally the same one
    TemplateDocxRenderer uses - what the preview shows is what exports.
    Shared by the main window preview and the template builder.
    """
    screenshots = list(screenshots or [])
    blocks: List[PreviewBlock] = []

    for section in template.enabled_sections(section_overrides):
        if section.show_title and section.title.strip():
            blocks.append(PreviewBlock(kind="doc_heading", text=context.resolve(section.title), level=1))
        for block in section.blocks:
            preview = _template_block_to_preview(block, context, screenshots)
            if preview is not None:
                blocks.append(preview)

    return blocks


def _template_block_to_preview(
    block: TemplateBlock,
    context: TemplateContext,
    screenshots: List[ScreenshotInfo],
) -> Optional[PreviewBlock]:
    kind = block.kind

    if kind in (BLOCK_HEADING, BLOCK_SUBHEADING):
        level = block.level if kind == BLOCK_HEADING else max(2, block.level)
        return PreviewBlock(kind="doc_heading", text=context.resolve(block.text), level=level)

    if kind == BLOCK_PARAGRAPH:
        return PreviewBlock(kind="paragraph", text=context.resolve(block.text))

    if kind == BLOCK_BULLET_LIST:
        items = [context.resolve(i) for i in block.items if i.strip()]
        if not items:
            return None
        return PreviewBlock(kind="bullet_list", bullets=items, ordered=block.ordered)

    if kind == BLOCK_TABLE:
        rows = [[context.resolve(cell) for cell in row] for row in block.table_rows]
        headers = [context.resolve(h) for h in block.table_headers] if block.include_headers else []
        if not rows and not headers:
            return None
        return PreviewBlock(
            kind="table",
            table_headers=headers,
            table_rows=rows,
            col_weights=block.normalized_col_weights(),
        )

    if kind == BLOCK_IMAGE:
        if not block.image_path:
            return None
        return PreviewBlock(kind="image", image_path=block.image_path, text=context.resolve(block.caption))

    if kind == BLOCK_SCREENSHOTS:
        if not screenshots:
            return None
        groups = group_screenshots_by_test_case(screenshots, context.test_cases)
        return PreviewBlock(
            kind="screenshots",
            heading=context.resolve(block.text) or "Screenshots",
            screenshot_groups=groups,
        )

    if kind == BLOCK_CODE:
        return PreviewBlock(kind="code", text=context.resolve(block.text))

    if kind == BLOCK_TWO_COLUMNS:
        columns = [context.resolve(c) for c in block.columns]
        return PreviewBlock(kind="two_columns", columns=columns)

    if kind == BLOCK_SEPARATOR:
        return PreviewBlock(kind="separator")

    return None
