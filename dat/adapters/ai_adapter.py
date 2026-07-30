import os
import json
import requests
from typing import List, Optional
from dat.models.doc_request import ChangeSummary

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

    def _generate_gemini_summary(self, title: str, changed_files: List[str], commits: List[str], raw_diff: str) -> ChangeSummary:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
        
        prompt = f"""
        You are a senior developer writing a feature summary for a project documentation.
        Feature Title: {title}
        Files Changed: {', '.join(changed_files)}
        Recent Commits: {', '.join(commits)}
        
        Code Diff:
        {raw_diff[:4000]} 

        Based on the code diff, generate a professional summary in JSON format with these keys:
        - "overview": A 1-2 sentence summary of what was achieved.
        - "key_points": A list of 1-3 extremely short bullet points (max 3 words each) explaining core logic.
        - "impact_areas": A list of 1-2 specific module or screen names affected (e.g. "Waste Screen", "Receiver Data").
        - "test_cases": A list of 2-3 one-line test cases (max 10 words each) describing what the code changes solve or verify.
        - "test_recommendations": A list of 2 QA steps.
        
        Return ONLY valid JSON.
        """

        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
        response.raise_for_status()
        
        result = response.json()
        text_content = result['candidates'][0]['content']['parts'][0]['text']
        
        # Clean JSON string (remove markdown blocks if present)
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
