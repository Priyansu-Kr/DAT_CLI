"""Persistence for user-authored custom document templates.

Templates live as one JSON file per template under ``~/.dat/templates``:

    ~/.dat/templates/<template_id>.template.json   one saved structure
    ~/.dat/templates/active.json                   pointer to the active one

One-file-per-template (instead of a single registry file) means a corrupt or
hand-edited file can only ever affect that template.
"""
import json
import os
from dataclasses import dataclass
from typing import List, Optional

from dat.adapters.filesystem_adapter import FilesystemAdapter
from dat.models.template_model import DocumentTemplate, TemplateError

TEMPLATE_SUFFIX = ".template.json"
ACTIVE_POINTER_FILE = "active.json"


@dataclass(frozen=True)
class TemplateSummary:
    """Lightweight listing entry (avoids holding every template in memory)."""
    template_id: str
    name: str
    updated_at: str
    section_count: int
    path: str


class TemplateStore:
    def __init__(self, fs: Optional[FilesystemAdapter] = None, base_dir: Optional[str] = None):
        self.fs = fs or FilesystemAdapter()
        self.base_dir = base_dir or os.path.join(os.path.expanduser("~"), ".dat", "templates")

    # --- Paths ----------------------------------------------------------

    def path_for(self, template_id: str) -> str:
        return os.path.join(self.base_dir, f"{self._safe_id(template_id)}{TEMPLATE_SUFFIX}")

    @staticmethod
    def _safe_id(template_id: str) -> str:
        """Guard against a crafted/corrupt id escaping the templates dir."""
        cleaned = "".join(ch for ch in str(template_id) if ch.isalnum() or ch in "-_")
        if not cleaned:
            raise TemplateError("Template id is empty or contains no usable characters.")
        return cleaned

    # --- Read -----------------------------------------------------------

    def list_templates(self) -> List[TemplateSummary]:
        """All readable templates, most recently updated first.

        Unreadable/corrupt files are skipped rather than raising - one bad
        file must not make the template picker unusable.
        """
        if not self.fs.exists(self.base_dir):
            return []

        summaries: List[TemplateSummary] = []
        for path in self.fs.list_files(self.base_dir, extensions=[TEMPLATE_SUFFIX]):
            try:
                template = self._read(path)
            except (TemplateError, OSError, ValueError) as e:
                print(f"[Warning] Skipping unreadable template {path}: {e}")
                continue
            summaries.append(TemplateSummary(
                template_id=template.template_id,
                name=template.name,
                updated_at=template.updated_at,
                section_count=len(template.sections),
                path=path,
            ))
        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    def load(self, template_id: str) -> DocumentTemplate:
        path = self.path_for(template_id)
        if not self.fs.exists(path):
            raise TemplateError(f"Template not found: {template_id}")
        return self._read(path)

    def _read(self, path: str) -> DocumentTemplate:
        raw = self.fs.read_text(path)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise TemplateError(f"Invalid template JSON: {e}") from e
        return DocumentTemplate.from_dict(data)

    def exists(self, template_id: str) -> bool:
        try:
            return self.fs.exists(self.path_for(template_id))
        except TemplateError:
            return False

    # --- Write ----------------------------------------------------------

    def save(self, template: DocumentTemplate) -> str:
        """Persist ``template`` (stamping updated_at) and return its path."""
        if not template.name.strip():
            raise TemplateError("Template name cannot be empty.")
        template.touch()
        path = self.path_for(template.template_id)
        self.fs.write_text_atomic(path, json.dumps(template.to_dict(), indent=2, ensure_ascii=False))
        return path

    def delete(self, template_id: str) -> bool:
        path = self.path_for(template_id)
        removed = self.fs.remove_file(path)
        if removed and self.get_active_id() == template_id:
            self.set_active_id(None)
        return removed

    # --- Active template pointer ----------------------------------------
    #
    # Remembering the active template is what lets the user reopen the app
    # and find the exact document structure they built last time.

    @property
    def _active_path(self) -> str:
        return os.path.join(self.base_dir, ACTIVE_POINTER_FILE)

    def get_active_id(self) -> Optional[str]:
        if not self.fs.exists(self._active_path):
            return None
        try:
            data = json.loads(self.fs.read_text(self._active_path))
            template_id = data.get("template_id") if isinstance(data, dict) else None
        except (json.JSONDecodeError, OSError):
            return None
        if not template_id:
            return None
        return str(template_id) if self.exists(str(template_id)) else None

    def set_active_id(self, template_id: Optional[str]) -> None:
        payload = {"template_id": template_id} if template_id else {}
        try:
            self.fs.write_text_atomic(self._active_path, json.dumps(payload, indent=2))
        except OSError as e:
            # A non-writable config dir must not break the session; the
            # user just loses the "remember my last template" convenience.
            print(f"[Warning] Could not persist active template: {e}")

    def load_active(self) -> Optional[DocumentTemplate]:
        template_id = self.get_active_id()
        if not template_id:
            return None
        try:
            return self.load(template_id)
        except (TemplateError, OSError) as e:
            print(f"[Warning] Could not load active template: {e}")
            return None
