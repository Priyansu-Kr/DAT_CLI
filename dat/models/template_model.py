"""Domain model for user-authored custom document templates.

A :class:`DocumentTemplate` is an ordered list of :class:`TemplateSection`,
each holding an ordered list of :class:`TemplateBlock` (heading, paragraph,
table, image, ...). It is the persisted, framework-agnostic description of
"the document structure the user built" - the GUI builder edits it, the
preview renders it, the DOCX renderer exports it, and the template store
serialises it to JSON.

Nothing here imports tkinter/docx, so the whole model is unit-testable
without a display or Word installed.
"""
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

# Bumped whenever the on-disk JSON shape changes in a non-additive way.
SCHEMA_VERSION = 1

# --- Block kinds ---------------------------------------------------------

BLOCK_HEADING = "heading"
BLOCK_SUBHEADING = "subheading"
BLOCK_PARAGRAPH = "paragraph"
BLOCK_BULLET_LIST = "bullet_list"
BLOCK_TABLE = "table"
BLOCK_IMAGE = "image"
BLOCK_SCREENSHOTS = "screenshots"
BLOCK_CODE = "code_block"
BLOCK_TWO_COLUMNS = "two_columns"
BLOCK_SEPARATOR = "separator"

GROUP_BASIC = "BASIC ELEMENTS"
GROUP_DATA = "DATA & MEDIA"
GROUP_LAYOUT = "LAYOUT UNITS"

# Columns are part of the document's *structure* (fixed when the template is
# designed); rows are *content* the reader adds while filling it in - hence a
# table is allowed to carry zero rows and grow later.
MIN_TABLE_ROWS, MAX_TABLE_ROWS = 0, 200
MIN_TABLE_COLS, MAX_TABLE_COLS = 1, 8
DEFAULT_TABLE_ROWS = 1

# Relative column widths: a [1, 4, 1] table gives its middle column four
# times the width of the outer two. Weights (rather than absolute widths)
# keep a table correct at any page size and in the on-screen preview alike.
MIN_COL_WEIGHT, MAX_COL_WEIGHT = 1, 12
DEFAULT_COL_WEIGHT = 1

MAX_HEADING_LEVEL = 3


class TemplateError(Exception):
    """Raised when a template cannot be parsed or is structurally invalid."""


@dataclass(frozen=True)
class BlockSpec:
    """Palette metadata for one block kind (single source of truth).

    Drives the component palette in the builder as well as validation, so
    adding a new block type never means editing a second parallel list.
    """
    kind: str
    label: str
    description: str
    icon: str
    group: str


BLOCK_SPECS: Tuple[BlockSpec, ...] = (
    BlockSpec(BLOCK_HEADING, "Heading", "H1, H2, or H3 section title", "H", GROUP_BASIC),
    BlockSpec(BLOCK_SUBHEADING, "Subheading", "Smaller title under a heading", "h", GROUP_BASIC),
    BlockSpec(BLOCK_PARAGRAPH, "Paragraph", "Standard text block with formatting", "¶", GROUP_BASIC),
    BlockSpec(BLOCK_BULLET_LIST, "Bullet List", "Unordered or ordered list items", "≔", GROUP_BASIC),
    BlockSpec(BLOCK_TABLE, "Table", "Structured data grid with headers", "▦", GROUP_DATA),
    BlockSpec(BLOCK_IMAGE, "Image", "Media block from library or URL", "▣", GROUP_DATA),
    BlockSpec(BLOCK_SCREENSHOTS, "Screenshots", "Auto-inserts the attached screenshots", "◫", GROUP_DATA),
    BlockSpec(BLOCK_CODE, "Code Block", "Syntax highlighted code snippet", "</>", GROUP_DATA),
    BlockSpec(BLOCK_TWO_COLUMNS, "Two Columns", "Split content into side-by-side cells", "⬓", GROUP_LAYOUT),
    BlockSpec(BLOCK_SEPARATOR, "Separator", "Subtle horizontal dividing line", "⎯", GROUP_LAYOUT),
)

BLOCK_SPEC_BY_KIND: Dict[str, BlockSpec] = {spec.kind: spec for spec in BLOCK_SPECS}

PALETTE_GROUPS: Tuple[str, ...] = (GROUP_BASIC, GROUP_DATA, GROUP_LAYOUT)


def block_specs_for_group(group: str) -> List[BlockSpec]:
    return [spec for spec in BLOCK_SPECS if spec.group == group]


def block_label(kind: str) -> str:
    spec = BLOCK_SPEC_BY_KIND.get(kind)
    return spec.label if spec else kind.replace("_", " ").title()


def new_id() -> str:
    """Short, collision-safe identifier for sections and blocks."""
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _as_str_list(value: Any) -> List[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v) for v in value]


_TOKEN_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
# A field holding nothing but one token - that is what turns a list token into
# one bullet (or one table row) per entry, rather than a comma-run of them all.
_SOLE_TOKEN_PATTERN = re.compile(r"^\s*\{\{\s*([a-zA-Z0-9_]+)\s*\}\}\s*$")

# Row-scoped: inside a table row being expanded by a list token, this numbers
# the generated rows. Deliberately absent from tokens() - outside such a row
# there is nothing to count, so it stays visible rather than resolving to "".
INDEX_TOKEN = "index"

# How much code the {{code_changes}} / {{code_diff}} tokens pull in. Far below
# the AI's diff budget: this lands in a document a person has to read, so it is
# an illustrative excerpt, not the whole patch.
CODE_TOKEN_MAX_FILES = 8
CODE_TOKEN_MAX_LINES_PER_FILE = 30
CODE_TOKEN_MAX_TOTAL_LINES = 120


def _tokens_in(text: Optional[str]) -> Set[str]:
    """Token names referenced by ``text``, lower-cased."""
    if not text:
        return set()
    return {match.group(1).lower() for match in _TOKEN_PATTERN.finditer(text)}


def _as_weight_list(value: Any) -> List[int]:
    """Parse stored column weights *positionally*.

    An unusable entry keeps its slot at the default rather than being
    dropped: dropping it would shift every later weight onto the wrong
    column, silently re-proportioning the table.
    """
    if not isinstance(value, (list, tuple)):
        return []
    weights: List[int] = []
    for item in value:
        try:
            weights.append(int(item))
        except (TypeError, ValueError):
            weights.append(DEFAULT_COL_WEIGHT)
    return weights


# --- Blocks --------------------------------------------------------------

@dataclass
class TemplateBlock:
    """A single renderable unit inside a section.

    One dataclass covers every block kind (rather than a class hierarchy)
    because blocks are edited generically in the builder, round-tripped
    through JSON, and switched on by ``kind`` in exactly two renderers -
    a flat shape keeps all three paths trivial.
    """
    kind: str
    block_id: str = field(default_factory=new_id)
    text: str = ""
    level: int = 2
    items: List[str] = field(default_factory=list)
    ordered: bool = False
    table_headers: List[str] = field(default_factory=list)
    table_rows: List[List[str]] = field(default_factory=list)
    col_weights: List[int] = field(default_factory=list)
    include_headers: bool = True
    image_path: str = ""
    caption: str = ""
    language: str = ""
    columns: List[str] = field(default_factory=list)

    # --- Factories ------------------------------------------------------

    @classmethod
    def create(cls, kind: str) -> "TemplateBlock":
        """Build a block of ``kind`` pre-filled with sensible placeholders."""
        if kind not in BLOCK_SPEC_BY_KIND:
            raise TemplateError(f"Unknown block kind: {kind!r}")

        if kind == BLOCK_HEADING:
            return cls(kind=kind, text="Section Heading", level=1)
        if kind == BLOCK_SUBHEADING:
            return cls(kind=kind, text="Subheading", level=2)
        if kind == BLOCK_PARAGRAPH:
            return cls(kind=kind, text="Describe the change here. Tokens like {{title}} are supported.")
        if kind == BLOCK_BULLET_LIST:
            return cls(kind=kind, items=["First point", "Second point"])
        if kind == BLOCK_TABLE:
            block = cls(kind=kind, table_headers=["Column 1", "Column 2"])
            block.set_table_size(DEFAULT_TABLE_ROWS, 2)
            return block
        if kind == BLOCK_IMAGE:
            return cls(kind=kind, caption="Figure caption")
        if kind == BLOCK_SCREENSHOTS:
            return cls(kind=kind, text="Screenshots")
        if kind == BLOCK_CODE:
            return cls(kind=kind, text="// code snippet", language="text")
        if kind == BLOCK_TWO_COLUMNS:
            return cls(kind=kind, columns=["Left column", "Right column"])
        return cls(kind=kind)

    def clone(self) -> "TemplateBlock":
        """Deep copy with a fresh id (used by 'duplicate block')."""
        data = self.to_dict()
        data["block_id"] = new_id()
        return TemplateBlock.from_dict(data)

    # --- Table helpers --------------------------------------------------

    @property
    def row_count(self) -> int:
        return len(self.table_rows)

    @property
    def col_count(self) -> int:
        if self.table_headers:
            return len(self.table_headers)
        return len(self.table_rows[0]) if self.table_rows else 0

    # --- Column widths --------------------------------------------------

    @staticmethod
    def _safe_weight(value: Any) -> int:
        try:
            weight = int(value)
        except (TypeError, ValueError):
            return DEFAULT_COL_WEIGHT
        return _clamp(weight, MIN_COL_WEIGHT, MAX_COL_WEIGHT)

    def normalized_col_weights(self) -> List[int]:
        """One valid weight per column, whatever is (or isn't) stored.

        Every renderer calls this instead of reading ``col_weights``, so a
        short, over-long or hand-edited list can never desync from the
        column count.
        """
        count = self.col_count
        weights = [self._safe_weight(w) for w in self.col_weights[:count]]
        while len(weights) < count:
            weights.append(DEFAULT_COL_WEIGHT)
        return weights

    def set_col_weight(self, col: int, weight: int) -> bool:
        weights = self.normalized_col_weights()
        if not 0 <= col < len(weights):
            return False
        weights[col] = self._safe_weight(weight)
        self.col_weights = weights
        return True

    def col_width_fractions(self) -> List[float]:
        """Each column's share of the table width (sums to 1.0)."""
        weights = self.normalized_col_weights()
        total = sum(weights)
        if not total:
            return []
        return [w / total for w in weights]

    def col_width_percentages(self) -> List[int]:
        return [int(round(f * 100)) for f in self.col_width_fractions()]

    def uses_equal_columns(self) -> bool:
        return len(set(self.normalized_col_weights())) <= 1

    def set_table_size(self, rows: int, cols: int) -> None:
        """Resize the grid, preserving any cell content that still fits."""
        rows = _clamp(int(rows), MIN_TABLE_ROWS, MAX_TABLE_ROWS)
        cols = _clamp(int(cols), MIN_TABLE_COLS, MAX_TABLE_COLS)

        headers = list(self.table_headers[:cols])
        while len(headers) < cols:
            headers.append(f"Column {len(headers) + 1}")
        self.table_headers = headers
        # col_count now reflects the new width, so weights re-normalise
        # against it (added columns default to an even share).
        self.col_weights = self.normalized_col_weights()

        grid: List[List[str]] = []
        for r in range(rows):
            existing = self.table_rows[r] if r < len(self.table_rows) else []
            row = list(existing[:cols])
            while len(row) < cols:
                row.append("")
            grid.append(row)
        self.table_rows = grid

    def add_row(self, index: Optional[int] = None) -> bool:
        """Append (or insert) an empty content row. False when at the cap."""
        if self.row_count >= MAX_TABLE_ROWS:
            return False
        blank = ["" for _ in range(max(self.col_count, MIN_TABLE_COLS))]
        if index is None or index >= len(self.table_rows):
            self.table_rows.append(blank)
        else:
            self.table_rows.insert(max(0, index), blank)
        return True

    def remove_row(self, index: int) -> bool:
        if not 0 <= index < len(self.table_rows):
            return False
        del self.table_rows[index]
        return True

    def set_cell(self, row: int, col: int, value: str) -> None:
        if 0 <= row < len(self.table_rows) and 0 <= col < len(self.table_rows[row]):
            self.table_rows[row][col] = value

    def set_header(self, col: int, value: str) -> None:
        if 0 <= col < len(self.table_headers):
            self.table_headers[col] = value

    # --- Serialisation --------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"block_id": self.block_id, "kind": self.kind}
        if self.kind in (BLOCK_HEADING, BLOCK_SUBHEADING):
            data.update(text=self.text, level=self.level)
        elif self.kind == BLOCK_PARAGRAPH:
            data.update(text=self.text)
        elif self.kind == BLOCK_BULLET_LIST:
            data.update(items=list(self.items), ordered=self.ordered)
        elif self.kind == BLOCK_TABLE:
            data.update(
                table_headers=list(self.table_headers),
                table_rows=[list(r) for r in self.table_rows],
                col_weights=self.normalized_col_weights(),
                include_headers=self.include_headers,
            )
        elif self.kind == BLOCK_IMAGE:
            data.update(image_path=self.image_path, caption=self.caption)
        elif self.kind == BLOCK_SCREENSHOTS:
            data.update(text=self.text)
        elif self.kind == BLOCK_CODE:
            data.update(text=self.text, language=self.language)
        elif self.kind == BLOCK_TWO_COLUMNS:
            data.update(columns=list(self.columns))
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemplateBlock":
        kind = str(data.get("kind") or "")
        if kind not in BLOCK_SPEC_BY_KIND:
            raise TemplateError(f"Unknown block kind: {kind!r}")

        block = cls(
            kind=kind,
            block_id=str(data.get("block_id") or new_id()),
            text=str(data.get("text") or ""),
            level=_clamp(int(data.get("level") or 2), 1, MAX_HEADING_LEVEL),
            items=_as_str_list(data.get("items")),
            ordered=bool(data.get("ordered", False)),
            table_headers=_as_str_list(data.get("table_headers")),
            col_weights=_as_weight_list(data.get("col_weights")),
            include_headers=bool(data.get("include_headers", True)),
            image_path=str(data.get("image_path") or ""),
            caption=str(data.get("caption") or ""),
            language=str(data.get("language") or ""),
            columns=_as_str_list(data.get("columns")),
        )
        raw_rows = data.get("table_rows")
        if isinstance(raw_rows, (list, tuple)):
            block.table_rows = [_as_str_list(row) for row in raw_rows]
        if kind == BLOCK_TABLE:
            # Normalise a hand-edited/legacy file into a rectangular grid,
            # keeping however many content rows it already had (possibly none).
            block.set_table_size(len(block.table_rows), max(block.col_count, MIN_TABLE_COLS))
        if kind == BLOCK_TWO_COLUMNS:
            while len(block.columns) < 2:
                block.columns.append("")
            block.columns = block.columns[:2]
        return block


# --- Editable content schema ---------------------------------------------
#
# Describes *what the reader types* into a block, as opposed to how the block
# is structured. The Control Center's content editor renders straight from
# these descriptors, so a new block kind becomes editable everywhere by
# extending content_fields() alone.

FIELD_LINE = "line"           # single-line text
FIELD_MULTILINE = "multiline"  # paragraph / code body
FIELD_LIST = "list"           # bullet or numbered items
FIELD_TABLE = "table"         # header row + cell grid
FIELD_PATH = "path"           # file path with a Browse affordance
FIELD_NOTE = "note"           # read-only explanation, no input

COLUMNS_KEY_PREFIX = "columns."


@dataclass(frozen=True)
class ContentField:
    """One editable piece of a block's content."""
    key: str
    label: str
    kind: str
    placeholder: str = ""


def content_fields(block: TemplateBlock) -> List[ContentField]:
    """Editable content descriptors for ``block``, in display order."""
    kind = block.kind

    if kind == BLOCK_HEADING:
        return [ContentField("text", "Heading", FIELD_LINE, "Heading text")]
    if kind == BLOCK_SUBHEADING:
        return [ContentField("text", "Subheading", FIELD_LINE, "Subheading text")]
    if kind == BLOCK_PARAGRAPH:
        return [ContentField("text", "Paragraph", FIELD_MULTILINE, "Paragraph text")]
    if kind == BLOCK_BULLET_LIST:
        return [
            ContentField("items", "List items", FIELD_LIST, "List item"),
            ContentField(
                "", "", FIELD_NOTE,
                "An item that is only {{test_cases}}, {{key_points}} or "
                "{{changed_files}} expands into one bullet per entry.",
            ),
        ]
    if kind == BLOCK_TABLE:
        return [
            ContentField("table", "Table cells", FIELD_TABLE),
            ContentField(
                "", "", FIELD_NOTE,
                "A row holding {{test_cases}} (or another list token) becomes one "
                "row per entry; put {{index}} in a cell to number them.",
            ),
        ]
    if kind == BLOCK_IMAGE:
        return [
            ContentField("image_path", "Image file", FIELD_PATH, "Image path"),
            ContentField("caption", "Caption", FIELD_LINE, "Caption (optional)"),
        ]
    if kind == BLOCK_SCREENSHOTS:
        return [
            ContentField("text", "Heading", FIELD_LINE, "Screenshots"),
            ContentField(
                "", "", FIELD_NOTE,
                "Pulls in the screenshots attached below, grouped by test case.",
            ),
        ]
    if kind == BLOCK_CODE:
        return [
            ContentField("language", "Language", FIELD_LINE, "e.g. python"),
            ContentField("text", "Code", FIELD_MULTILINE, "Code snippet"),
            ContentField(
                "", "", FIELD_NOTE,
                "Use {{code_changes}} for the code your branch added, or "
                "{{code_diff}} for it in patch form. Both come from git, so "
                "they work without an API key.",
            ),
        ]
    if kind == BLOCK_TWO_COLUMNS:
        return [
            ContentField(f"{COLUMNS_KEY_PREFIX}0", "Left column", FIELD_MULTILINE, "Left column text"),
            ContentField(f"{COLUMNS_KEY_PREFIX}1", "Right column", FIELD_MULTILINE, "Right column text"),
        ]
    return []  # separator and anything unknown carry no content


def has_editable_content(block: TemplateBlock) -> bool:
    return any(field.kind != FIELD_NOTE for field in content_fields(block))


def get_content(block: TemplateBlock, key: str):
    """Read a content field named by a ContentField key."""
    if key.startswith(COLUMNS_KEY_PREFIX):
        index = int(key[len(COLUMNS_KEY_PREFIX):])
        return block.columns[index] if index < len(block.columns) else ""
    return getattr(block, key, "")


def set_content(block: TemplateBlock, key: str, value) -> None:
    """Write a content field named by a ContentField key."""
    if key.startswith(COLUMNS_KEY_PREFIX):
        index = int(key[len(COLUMNS_KEY_PREFIX):])
        columns = list(block.columns)
        while len(columns) <= index:
            columns.append("")
        columns[index] = value
        block.columns = columns[:2]
        return
    if key == "items":
        block.items = [str(v) for v in value]
        return
    if not hasattr(block, key):
        raise TemplateError(f"Unknown content field {key!r} for block kind {block.kind!r}")
    setattr(block, key, value)


# --- Sections ------------------------------------------------------------

@dataclass
class TemplateSection:
    """A named, individually show/hide-able group of blocks."""
    title: str = "New Section"
    section_id: str = field(default_factory=new_id)
    enabled: bool = True
    show_title: bool = True
    blocks: List[TemplateBlock] = field(default_factory=list)

    def add_block(self, block: TemplateBlock, index: Optional[int] = None) -> TemplateBlock:
        if index is None or index >= len(self.blocks):
            self.blocks.append(block)
        else:
            self.blocks.insert(max(0, index), block)
        return block

    def remove_block(self, block_id: str) -> bool:
        before = len(self.blocks)
        self.blocks = [b for b in self.blocks if b.block_id != block_id]
        return len(self.blocks) != before

    def find_block(self, block_id: str) -> Optional[TemplateBlock]:
        return next((b for b in self.blocks if b.block_id == block_id), None)

    def move_block(self, block_id: str, delta: int) -> bool:
        """Shift a block by ``delta`` positions. Returns True if it moved."""
        index = next((i for i, b in enumerate(self.blocks) if b.block_id == block_id), None)
        if index is None:
            return False
        target = index + delta
        if not 0 <= target < len(self.blocks):
            return False
        self.blocks.insert(target, self.blocks.pop(index))
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "enabled": self.enabled,
            "show_title": self.show_title,
            "blocks": [b.to_dict() for b in self.blocks],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemplateSection":
        blocks: List[TemplateBlock] = []
        for raw in data.get("blocks") or []:
            if not isinstance(raw, dict):
                continue
            try:
                blocks.append(TemplateBlock.from_dict(raw))
            except TemplateError:
                # Forward compatibility: a block kind written by a newer
                # version is skipped rather than failing the whole load.
                continue
        return cls(
            section_id=str(data.get("section_id") or new_id()),
            title=str(data.get("title") or "Untitled Section"),
            enabled=bool(data.get("enabled", True)),
            show_title=bool(data.get("show_title", True)),
            blocks=blocks,
        )


# --- Template ------------------------------------------------------------

@dataclass
class DocumentTemplate:
    """A complete, persistable custom document structure."""
    name: str = "New Document Template"
    template_id: str = field(default_factory=new_id)
    description: str = ""
    sections: List[TemplateSection] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    # --- Structure ------------------------------------------------------

    def add_section(self, section: Optional[TemplateSection] = None, index: Optional[int] = None) -> TemplateSection:
        section = section or TemplateSection(title=f"Section {len(self.sections) + 1}")
        if index is None or index >= len(self.sections):
            self.sections.append(section)
        else:
            self.sections.insert(max(0, index), section)
        return section

    def remove_section(self, section_id: str) -> bool:
        before = len(self.sections)
        self.sections = [s for s in self.sections if s.section_id != section_id]
        return len(self.sections) != before

    def find_section(self, section_id: str) -> Optional[TemplateSection]:
        return next((s for s in self.sections if s.section_id == section_id), None)

    def move_section(self, section_id: str, delta: int) -> bool:
        index = next((i for i, s in enumerate(self.sections) if s.section_id == section_id), None)
        if index is None:
            return False
        target = index + delta
        if not 0 <= target < len(self.sections):
            return False
        self.sections.insert(target, self.sections.pop(index))
        return True

    def locate_block(self, block_id: str) -> Optional[Tuple[TemplateSection, TemplateBlock]]:
        for section in self.sections:
            block = section.find_block(block_id)
            if block is not None:
                return section, block
        return None

    @property
    def block_count(self) -> int:
        return sum(len(s.blocks) for s in self.sections)

    def enabled_sections(self, overrides: Optional[Dict[str, bool]] = None) -> List[TemplateSection]:
        """Sections that should render, honouring runtime toggle overrides."""
        overrides = overrides or {}
        return [s for s in self.sections if overrides.get(s.section_id, s.enabled)]

    def referenced_tokens(self) -> Set[str]:
        """Lower-cased `{{token}}` names used anywhere in this template.

        Lets the Control Center show exactly the shared inputs this document
        needs (e.g. Created By only when something writes `{{author}}`)
        instead of every field the built-in layout happens to use.
        """
        found: Set[str] = set()
        for section in self.sections:
            found.update(_tokens_in(section.title))
            for block in section.blocks:
                for value in (block.text, block.caption):
                    found.update(_tokens_in(value))
                for item in block.items:
                    found.update(_tokens_in(item))
                for header in block.table_headers:
                    found.update(_tokens_in(header))
                for row in block.table_rows:
                    for cell in row:
                        found.update(_tokens_in(cell))
                for column in block.columns:
                    found.update(_tokens_in(column))
        return found

    def touch(self) -> None:
        self.updated_at = _now_iso()

    def copy(self) -> "DocumentTemplate":
        return DocumentTemplate.from_dict(self.to_dict())

    def duplicate(self, name: Optional[str] = None) -> "DocumentTemplate":
        """Independent copy carrying fresh ids (a distinct saved template)."""
        clone = self.copy()
        clone.template_id = new_id()
        clone.name = name or f"{self.name} (Copy)"
        clone.created_at = _now_iso()
        clone.updated_at = clone.created_at
        for section in clone.sections:
            section.section_id = new_id()
            for block in section.blocks:
                block.block_id = new_id()
        return clone

    # --- Serialisation --------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "sections": [s.to_dict() for s in self.sections],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "DocumentTemplate":
        if not isinstance(data, dict):
            raise TemplateError("Template file must contain a JSON object.")

        version = data.get("schema_version", SCHEMA_VERSION)
        try:
            version = int(version)
        except (TypeError, ValueError):
            raise TemplateError(f"Invalid schema_version: {data.get('schema_version')!r}")
        if version > SCHEMA_VERSION:
            raise TemplateError(
                f"Template was created by a newer version of DAT "
                f"(schema {version}, supported {SCHEMA_VERSION})."
            )

        raw_sections = data.get("sections")
        if raw_sections is not None and not isinstance(raw_sections, (list, tuple)):
            raise TemplateError("Template 'sections' must be a list.")

        template = cls(
            template_id=str(data.get("template_id") or new_id()),
            name=str(data.get("name") or "Untitled Template"),
            description=str(data.get("description") or ""),
            created_at=str(data.get("created_at") or _now_iso()),
            updated_at=str(data.get("updated_at") or _now_iso()),
            sections=[TemplateSection.from_dict(s) for s in (raw_sections or []) if isinstance(s, dict)],
        )
        template._ensure_unique_ids()
        return template

    def _ensure_unique_ids(self) -> None:
        """Repair duplicate ids (hand-edited or badly merged files).

        Ids are the identity used by every builder/preview/toggle lookup, so
        a duplicate would silently edit or hide the wrong element.
        """
        seen = set()
        for section in self.sections:
            if section.section_id in seen:
                section.section_id = new_id()
            seen.add(section.section_id)
            for block in section.blocks:
                if block.block_id in seen:
                    block.block_id = new_id()
                seen.add(block.block_id)

    # --- Starter content ------------------------------------------------

    @classmethod
    def starter(cls, name: str = "New Document Template") -> "DocumentTemplate":
        """A minimal but non-empty template so the canvas is never blank.

        Placeholders are deliberately generic - seeding `{{title}}`/`{{ticket_id}}`
        here made a brand-new structure open showing the *previous* document's
        title, which reads like content leaked across documents.
        """
        section = TemplateSection(title="Section 1")
        section.add_block(TemplateBlock(kind=BLOCK_HEADING, text="Section Heading", level=1))
        section.add_block(TemplateBlock(kind=BLOCK_PARAGRAPH, text="Add your content here."))
        return cls(name=name, sections=[section])


# --- Code excerpts from the diff -----------------------------------------

def _file_sections(raw_diff: str) -> List[Tuple[str, List[str]]]:
    """Split a unified diff into (path, lines) per file, in git's order."""
    sections: List[Tuple[str, List[str]]] = []
    path = ""
    lines: List[str] = []

    for line in (raw_diff or "").splitlines():
        header = re.match(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$", line)
        if header:
            if path:
                sections.append((path, lines))
            path = header.group("b") or header.group("a")
            lines = []
        elif path:
            lines.append(line)

    if path:
        sections.append((path, lines))
    return sections


def _excerpt(
    raw_diff: str,
    keep,
    clean,
    max_files: int = CODE_TOKEN_MAX_FILES,
    max_lines_per_file: int = CODE_TOKEN_MAX_LINES_PER_FILE,
    max_total_lines: int = CODE_TOKEN_MAX_TOTAL_LINES,
) -> str:
    """Per-file excerpt of a diff, bounded on every axis.

    ``keep`` decides which diff lines belong in the output and ``clean`` turns
    one into its printed form - the only difference between the "just the new
    code" and "the patch" views.
    """
    out: List[str] = []
    budget = max_total_lines
    sections = _file_sections(raw_diff)

    for path, lines in sections[:max_files]:
        if budget <= 0:
            break
        body = [clean(line) for line in lines if keep(line)]
        if not body:
            continue  # a mode change or a binary file: nothing to show

        allowed = min(max_lines_per_file, budget)
        shown, dropped = body[:allowed], len(body) - min(len(body), allowed)
        budget -= len(shown)

        # A separator rather than a comment: no comment syntax is right for
        # every language a repository might hold.
        out.append(f"==== {path} ====")
        out.extend(shown)
        if dropped:
            out.append(f"... {dropped} more changed line(s) in this file ...")
        out.append("")

    remaining_files = max(0, len(sections) - max_files)
    if remaining_files:
        out.append(f"... and {remaining_files} more changed file(s) ...")

    return "\n".join(out).strip()


def added_code_from_diff(raw_diff: str, **limits) -> str:
    """The code this branch *added*, per file, with the diff's '+' stripped.

    Reads as source rather than as a patch, which is what a feature document
    wants. Available whether or not an AI provider is configured - it comes
    from git, not from a model.
    """
    return _excerpt(
        raw_diff,
        keep=lambda line: line.startswith("+") and not line.startswith("+++"),
        clean=lambda line: line[1:],
        **limits,
    )


def diff_excerpt(raw_diff: str, **limits) -> str:
    """The same excerpt in patch form: additions, removals and hunk headers."""
    return _excerpt(
        raw_diff,
        keep=lambda line: (
            line.startswith(("+", "-", "@@")) and not line.startswith(("+++", "---"))
        ),
        clean=lambda line: line,
        **limits,
    )


# --- Render context ------------------------------------------------------

@dataclass
class TemplateContext:
    """Live values substituted into ``{{token}}`` placeholders at render time.

    Shared by the GUI preview and the DOCX renderer so a template always
    resolves identically in both.
    """
    title: str = ""
    ticket_id: str = ""
    topic: str = ""
    author: str = ""
    approved_by: str = ""
    branch: str = ""
    date: str = field(default_factory=lambda: datetime.now().strftime("%d-%B-%Y"))
    key_points: List[str] = field(default_factory=list)
    impact_areas: List[str] = field(default_factory=list)
    test_cases: List[str] = field(default_factory=list)
    test_recommendations: List[str] = field(default_factory=list)
    changed_files: List[str] = field(default_factory=list)
    # The branch diff, so a Code Block can show the code that actually
    # changed. Excerpted lazily - most templates never ask for it.
    raw_diff: str = ""
    _token_cache: Optional[Dict[str, str]] = field(
        default=None, repr=False, compare=False
    )

    def list_tokens(self) -> Dict[str, List[str]]:
        """Tokens whose value is a list, and can therefore expand into one
        bullet or one table row per entry."""
        return {
            "key_points": list(self.key_points),
            "impact_areas": list(self.impact_areas),
            "modules": list(self.impact_areas),
            "test_cases": list(self.test_cases),
            "test_recommendations": list(self.test_recommendations),
            "changed_files": list(self.changed_files),
        }

    def tokens(self) -> Dict[str, str]:
        if self._token_cache is not None:
            return self._token_cache

        values = {
            "title": self.title,
            "ticket_id": self.ticket_id,
            "ticket": self.ticket_id,
            "topic": self.topic,
            "author": self.author,
            "approved_by": self.approved_by,
            "branch": self.branch,
            "date": self.date,
            # Inline form: every list token also works mid-sentence.
            **{name: ", ".join(items) for name, items in self.list_tokens().items()},
            # Code straight from git - no AI provider involved.
            "code_changes": added_code_from_diff(self.raw_diff),
            "code_diff": diff_excerpt(self.raw_diff),
        }
        # Cached because the code tokens re-parse the diff, and resolve() runs
        # once per text field on every keystroke-driven preview refresh.
        self._token_cache = values
        return values

    def expand_list(self, text: Optional[str]) -> Optional[List[str]]:
        """The entries a field should become when it holds nothing but one list
        token, else None (meaning: resolve it as ordinary text)."""
        if not text:
            return None
        match = _SOLE_TOKEN_PATTERN.match(text)
        if not match:
            return None
        return self.list_tokens().get(match.group(1).lower())

    def resolve_items(self, items: List[str]) -> List[str]:
        """Resolve list-field entries, expanding any that are a list token.

        An empty list token contributes nothing rather than a blank bullet -
        with no API key there are no test cases, and the document should simply
        not carry an empty item.
        """
        resolved: List[str] = []
        for item in items:
            if not (item or "").strip():
                continue
            expanded = self.expand_list(item)
            if expanded is None:
                resolved.append(self.resolve(item))
            else:
                resolved.extend(entry for entry in expanded if entry.strip())
        return resolved

    def resolve_rows(self, rows: List[List[str]]) -> List[List[str]]:
        """Resolve table rows, expanding a row that holds a list token into one
        row per entry ({{index}} numbers them)."""
        out: List[List[str]] = []

        for row in rows:
            position, entries = -1, None
            for index, cell in enumerate(row):
                expanded = self.expand_list(cell)
                if expanded is not None:
                    position, entries = index, expanded
                    break

            if entries is None:
                out.append([self.resolve(cell) for cell in row])
                continue

            for number, entry in enumerate(entries, start=1):
                out.append([
                    entry if index == position
                    else str(number) if self._is_token(cell, INDEX_TOKEN)
                    else self.resolve(cell)
                    for index, cell in enumerate(row)
                ])

        return out

    @staticmethod
    def _is_token(text: Optional[str], name: str) -> bool:
        match = _SOLE_TOKEN_PATTERN.match(text or "")
        return bool(match and match.group(1).lower() == name)

    def resolve(self, text: Optional[str]) -> str:
        """Substitute known tokens; unknown ones are left verbatim so a typo
        is visible in the preview instead of silently deleting content."""
        if not text:
            return ""
        available = self.tokens()

        def replace(match: "re.Match") -> str:
            key = match.group(1).lower()
            return available.get(key, match.group(0))

        return _TOKEN_PATTERN.sub(replace, text)


SUPPORTED_TOKENS: Tuple[str, ...] = tuple(sorted(TemplateContext().tokens().keys()))

# Grouped by behaviour, for anything that has to explain them to a user.
LIST_TOKENS: Tuple[str, ...] = tuple(sorted(TemplateContext().list_tokens().keys()))
CODE_TOKENS: Tuple[str, ...] = ("code_changes", "code_diff")
VALUE_TOKENS: Tuple[str, ...] = tuple(
    sorted(set(SUPPORTED_TOKENS) - set(LIST_TOKENS) - set(CODE_TOKENS))
)
