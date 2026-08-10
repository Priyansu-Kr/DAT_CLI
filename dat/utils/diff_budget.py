"""Fitting a large diff into a bounded prompt.

A flat `diff[:N]` slice spends the whole budget on whichever file git printed
first, so a 13-file change is summarised from one file and the AI never learns
the rest exist. This module instead splits the diff per file, gives each file
a share of the budget, and reports exactly what it had to leave out - so the
prompt can say "9 files omitted" rather than implying completeness.

Pure text processing: no git, no network, no I/O.
"""
import os
import re
from dataclasses import dataclass, field
from typing import List, Tuple

# Roughly 50k tokens of diff - a small fraction of the model's context window,
# but enough that a multi-file feature is summarised from most of its code
# rather than the first hunk of each file. Still bounded, because cost and
# latency both scale with it, and the answer deadline is finite.
DEFAULT_DIFF_CHAR_BUDGET = 200_000
DIFF_CHAR_BUDGET_ENV_VAR = "DAT_AI_DIFF_CHAR_BUDGET"

# Below this, a file's slice is too small to show anything meaningful, so the
# file is reported as omitted instead of being included as a stub.
MIN_CHARS_PER_FILE = 400

_FILE_HEADER = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")
# Lines that must survive trimming: without them a section is unattributable.
_METADATA_PREFIXES = (
    "diff --git ", "new file mode", "deleted file mode", "old mode", "new mode",
    "similarity index", "rename from", "rename to", "copy from", "copy to",
    "index ", "--- ", "+++ ", "Binary files ",
)


def resolve_char_budget(explicit: int = None) -> int:
    """Budget to use: explicit argument, else $DAT_AI_DIFF_CHAR_BUDGET, else
    the default. Invalid or non-positive overrides fall back to the default."""
    if explicit is not None and explicit > 0:
        return explicit
    raw = os.environ.get(DIFF_CHAR_BUDGET_ENV_VAR)
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_DIFF_CHAR_BUDGET


@dataclass
class DiffPackStats:
    """What made it into the packed diff, and what did not."""
    total_chars: int = 0
    packed_chars: int = 0
    total_files: int = 0
    included_files: int = 0
    truncated_files: List[str] = field(default_factory=list)
    omitted_files: List[str] = field(default_factory=list)

    @property
    def omitted_file_count(self) -> int:
        return len(self.omitted_files)

    @property
    def is_complete(self) -> bool:
        return not self.truncated_files and not self.omitted_files

    def describe(self) -> str:
        """One-line account of the trimming, for the prompt itself."""
        if self.total_files == 0:
            return "No code diff was available."
        if self.is_complete:
            return f"Complete diff for all {self.total_files} changed file(s)."

        parts = [
            f"Diff truncated to fit: {self.included_files} of {self.total_files} "
            f"file(s) included ({self.packed_chars} of {self.total_chars} characters)."
        ]
        if self.truncated_files:
            parts.append("Partially shown: " + ", ".join(self.truncated_files) + ".")
        if self.omitted_files:
            parts.append("Not shown at all: " + ", ".join(self.omitted_files) + ".")
        parts.append(
            "Treat the omitted files as changed but unseen - do not claim they were unaffected."
        )
        return " ".join(parts)


def split_diff_by_file(diff: str) -> List[Tuple[str, str]]:
    """Split a unified diff into (path, section) pairs, in git's order."""
    if not diff.strip():
        return []

    sections: List[Tuple[str, str]] = []
    current_path = None
    current: List[str] = []

    for line in diff.splitlines():
        match = _FILE_HEADER.match(line)
        if match:
            if current:
                sections.append((current_path or "(unknown)", "\n".join(current)))
            current_path = match.group("b") or match.group("a")
            current = [line]
        else:
            current.append(line)

    if current:
        sections.append((current_path or "(unknown)", "\n".join(current)))
    return sections


def _trim_section(section: str, budget: int) -> Tuple[str, bool]:
    """Trim one file's section to ``budget`` characters.

    Metadata lines are always kept so the file stays identifiable; the body
    is then filled in order and the remainder marked. Returns the trimmed
    text and whether anything was dropped.
    """
    if len(section) <= budget:
        return section, False

    lines = section.splitlines()
    metadata = [line for line in lines if line.startswith(_METADATA_PREFIXES)]
    body = lines[len(metadata):]

    kept = list(metadata)
    used = sum(len(line) + 1 for line in kept)
    dropped = 0

    for line in body:
        cost = len(line) + 1
        if used + cost > budget:
            dropped += 1
            continue
        kept.append(line)
        used += cost

    if dropped:
        kept.append(f"... {dropped} more diff line(s) in this file omitted ...")
    return "\n".join(kept), True


def pack_diff(diff: str, budget_chars: int = None) -> Tuple[str, DiffPackStats]:
    """Fit ``diff`` into ``budget_chars``, spreading the space across files.

    Every changed file gets an equal share, so a summary is informed by the
    whole change rather than by whichever file came first. Files that cannot
    be given a useful share are reported in the stats instead.
    """
    budget = resolve_char_budget(budget_chars)
    sections = split_diff_by_file(diff)
    stats = DiffPackStats(total_chars=len(diff), total_files=len(sections))

    if not sections:
        return "", stats
    if len(diff) <= budget:
        stats.packed_chars = len(diff)
        stats.included_files = len(sections)
        return diff, stats

    # How many files can each get a usable share?
    includable = max(1, min(len(sections), budget // MIN_CHARS_PER_FILE))
    stats.omitted_files = [path for path, _ in sections[includable:]]
    selected = sections[:includable]
    per_file = budget // len(selected)

    packed: List[str] = []
    spent = 0
    for path, section in selected:
        # Hand any share a small file didn't use to the files after it.
        remaining_files = len(selected) - len(packed)
        allowance = max(per_file, (budget - spent) // max(1, remaining_files))
        trimmed, was_trimmed = _trim_section(section, allowance)
        if was_trimmed:
            stats.truncated_files.append(path)
        packed.append(trimmed)
        spent += len(trimmed) + 1

    result = "\n".join(packed)
    stats.packed_chars = len(result)
    stats.included_files = len(selected)
    return result, stats
