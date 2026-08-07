import os
import json
import requests
from typing import List, Optional
from dat.models.doc_request import ChangeSummary
from dat.utils.diff_budget import pack_diff

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODEL = "gemini-1.5-flash"
GEMINI_MAX_OUTPUT_TOKENS = 2048
# Separate connect/read timeouts: a dead host should fail fast, while a
# large diff legitimately takes a while to summarise.
GEMINI_CONNECT_TIMEOUT = 10
GEMINI_READ_TIMEOUT = 90


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
        if self.provider == "gemini" and self.api_key:
            try:
                return self._generate_gemini_summary(title, changed_files, commits, raw_diff)
            except Exception as e:
                print(f"[Warning] Gemini AI failed, falling back to rule-based: {e}")
        
        return self._generate_rule_based_summary(title, changed_files, commits, raw_diff)

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
            timeout=(GEMINI_CONNECT_TIMEOUT, GEMINI_READ_TIMEOUT),
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
            test_cases=data.get("test_cases", [])
        )

    LANGUAGE_EXTENSIONS = {
        ".py": "Python",
        ".kt": "Kotlin",
        ".java": "Java",
        ".swift": "Swift",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".xml": "UI/Layout",
        ".html": "HTML",
        ".css": "CSS",
    }

    def _generate_rule_based_summary(self, title: str, changed_files: List[str], commits: List[str], raw_diff: str) -> ChangeSummary:
        overview = f"Implemented {title} updates across {len(changed_files)} workspace files."

        languages = []
        for f in changed_files:
            lang = self.LANGUAGE_EXTENSIONS.get(os.path.splitext(f)[1].lower())
            if lang and lang not in languages:
                languages.append(lang)

        key_points = [f"Updated {lang} logic" for lang in languages[:2]] or ["Updated core logic"]
        key_points.append("Verified UI changes")

        return ChangeSummary(
            overview=overview,
            key_points=key_points,
            impact_areas=["Main Module"],
            test_recommendations=["Verify feature on emulator"],
            test_cases=["Verify that core feature requirements are met", "Ensure UI elements are displayed correctly"]
        )
