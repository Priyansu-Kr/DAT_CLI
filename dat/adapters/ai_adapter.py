import os
import json
import requests
from typing import List, Optional
from dat.models.doc_request import (
    SUMMARY_SOURCE_AI,
    SUMMARY_SOURCE_GIT_DIFF,
    ChangeSummary,
)
from dat.utils.diff_budget import pack_diff, resolve_char_budget

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_MAX_OUTPUT_TOKENS = 8192
# A dead host should fail fast, so the connect timeout stays short and fixed.
GEMINI_CONNECT_TIMEOUT = 10

# How long to wait for the model's answer. Short by default - a user watching
# the Preview Panel will not wait out a 90-second stall, and content built
# from the Git diff is on screen already - but scaled up for genuinely large
# prompts, so a 20-file refactor isn't guaranteed to miss its own deadline.
AI_DEADLINE_BASE_SECONDS = 15
AI_DEADLINE_EXTRA_PER_100K_CHARS = 5
AI_DEADLINE_MAX_SECONDS = 45
AI_DEADLINE_ENV_VAR = "DAT_AI_TIMEOUT_SECONDS"


def resolve_ai_deadline(prompt_chars: int = 0) -> float:
    """Seconds to wait for a summary of a prompt this size.

    $DAT_AI_TIMEOUT_SECONDS pins it to a fixed value for users who would
    rather wait than fall back (or who want to fail faster).
    """
    raw = os.environ.get(AI_DEADLINE_ENV_VAR)
    if raw:
        try:
            override = float(raw)
            if override > 0:
                return override
        except ValueError:
            pass

    extra = (max(0, prompt_chars) // 100_000) * AI_DEADLINE_EXTRA_PER_100K_CHARS
    return float(min(AI_DEADLINE_MAX_SECONDS, AI_DEADLINE_BASE_SECONDS + extra))


def deadline_for_diff(raw_diff: str) -> float:
    """The deadline a diff this size will get, for callers (the GUI) that need
    to know before the prompt exists. The diff dominates the prompt, and it
    can never contribute more than the packed-diff budget."""
    return resolve_ai_deadline(min(len(raw_diff or ""), resolve_char_budget()))


def _path_suffix(path: str, segments: int) -> str:
    """The last `segments` parts of a path ("collector/src/Repository.kt")."""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    return "/".join(parts[-segments:]) if parts else path


def changed_file_display_names(changed_files: List[str]) -> List[str]:
    """Changed paths as short, document-friendly names ("SyncService.kt").

    Two changed files can share a basename (module-per-directory projects do
    this constantly), and a bare name would then read as a duplicate bullet.
    Those, and only those, grow leftwards - one directory at a time - until
    each is distinguishable, so a reader can tell which Repository.kt is which
    without every other bullet carrying a path it doesn't need.
    """
    groups: dict = {}
    for path in changed_files:
        groups.setdefault(os.path.basename(path) or path, []).append(path)

    display: dict = {}
    for basename, paths in groups.items():
        if len(paths) == 1:
            display[paths[0]] = basename
            continue

        longest = max(len(p.replace("\\", "/").split("/")) for p in paths)
        for depth in range(2, longest + 1):
            candidates = {path: _path_suffix(path, depth) for path in paths}
            if len(set(candidates.values())) == len(paths):
                break  # every one of them is now unique
        display.update(candidates)

    # dict.fromkeys: de-duplicate while keeping git's ordering.
    return list(dict.fromkeys(display[path] for path in changed_files))


def build_git_diff_summary(title: str, changed_files: List[str]) -> ChangeSummary:
    """Document content derived purely from the Git diff - no AI involved.

    This is the fallback pillar for users without a Gemini key: the files the
    work touched *are* the "Changes Done" section, and nothing is invented on
    their behalf. Test cases are deliberately left empty for the user to fill
    in (in the Preview Panel or the exported document) - guessing them
    without reading the code produces filler a tester can't act on.
    """
    names = changed_file_display_names(changed_files)

    if names:
        overview = (
            f"Implemented {title} across {len(names)} "
            f"{'file' if len(names) == 1 else 'files'}."
        )
    else:
        overview = f"Implemented {title}. No changed files were detected in this repository."

    return ChangeSummary(
        overview=overview,
        key_points=names,
        impact_areas=[],
        test_recommendations=[],
        test_cases=[],
        source=SUMMARY_SOURCE_GIT_DIFF,
    )


class AIAdapter:
    def __init__(self, provider: str = "gemini", api_key: Optional[str] = None):
        self.provider = provider or "gemini"
        self.api_key = api_key

    def generate_summary(
        self,
        title: str,
        changed_files: List[str],
        commits: List[str],
        raw_diff: str
    ) -> ChangeSummary:
        # A saved key always means the Gemini pillar - the key's presence is
        # the switch, so a stale provider value can't strand a configured
        # user on the Git-diff path.
        if self.api_key:
            try:
                return self._generate_gemini_summary(title, changed_files, commits, raw_diff)
            except Exception as e:
                print(f"[Warning] Gemini AI failed, falling back to the Git diff: {e}")

        return build_git_diff_summary(title, changed_files)

    def _build_prompt(self, title: str, changed_files: List[str], commits: List[str], raw_diff: str) -> str:
        packed_diff, stats = pack_diff(raw_diff)

        # How much to ask for scales with the size of the change: a two-file
        # tweak doesn't need six test cases, and a twenty-file feature isn't
        # described by two.
        file_count = max(len(changed_files), stats.total_files)
        if file_count <= 2:
            points, cases = "2-3", "3-4"
        elif file_count <= 8:
            points, cases = "3-5", "4-6"
        else:
            points, cases = "4-6", "5-8"

        return f"""You are a senior developer writing the summary section of feature documentation.

Feature Title: {title}
Files Changed ({len(changed_files)}): {', '.join(changed_files) or 'unknown'}
Commits on this branch: {'; '.join(commits) or 'none'}

Diff coverage: {stats.describe()}

Code Diff:
{packed_diff}

Using the diff, the file names and the commit messages together, return a JSON object with:
- "overview": 1-2 sentences on what was achieved.
- "key_points": {points} bullet points naming what changed and where (max 14 words each).
  Prefer concrete specifics ("AddAnnouncementActivity: new Collector receiver type") over
  vague ones ("updated logic").
- "impact_areas": the specific modules/screens affected, named as a user or QA would say them.
- "test_cases": {cases} one-line test cases that verify these changes (max 16 words each).
  Each must be checkable by a tester without reading the code.
- "test_recommendations": 2-3 QA steps.

Base every item on evidence in the diff, file names or commits. Where a file was omitted from
the diff above, you may still reference it by name from the file list, but do not invent its
contents. Return ONLY valid JSON."""

    def _generate_gemini_summary(self, title: str, changed_files: List[str], commits: List[str], raw_diff: str) -> ChangeSummary:
        url = f"{GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent"
        prompt = self._build_prompt(title, changed_files, commits, raw_diff)

        response = requests.post(
            url,
            # Key in a header rather than the query string, so it can't be
            # captured by proxy/access logs along the way.
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                # Ask for JSON directly instead of parsing it out of prose.
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
                },
            },
            # Without a timeout a hung connection blocks the CLI indefinitely.
            # The read half doubles as the answer deadline: when it expires,
            # callers fall back to the Git-diff summary.
            timeout=(GEMINI_CONNECT_TIMEOUT, resolve_ai_deadline(len(prompt))),
        )
        response.raise_for_status()

        result = response.json()
        text_content = result['candidates'][0]['content']['parts'][0]['text']

        # response_mime_type should make this exact, but older models and
        # proxies still wrap JSON in markdown fences - tolerate both.
        clean_json = text_content.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)

        return ChangeSummary(
            overview=data.get("overview", ""),
            key_points=data.get("key_points", []),
            impact_areas=data.get("impact_areas", []),
            test_recommendations=data.get("test_recommendations", []),
            test_cases=data.get("test_cases", []),
            source=SUMMARY_SOURCE_AI,
        )

    def _generate_git_diff_summary(self, title: str, changed_files: List[str]) -> ChangeSummary:
        """Kept as a method for callers that hold an adapter; the real work
        lives in the module-level build_git_diff_summary so code without an
        adapter (e.g. the GUI's failure fallback) can reuse it."""
        return build_git_diff_summary(title, changed_files)
