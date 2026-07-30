import os
from dat.renderers.base_renderer import BaseRenderer
from dat.models.doc_request import DocRequest

class MarkdownRenderer(BaseRenderer):
    def render(self, doc_request: DocRequest) -> str:
        lines = []
        lines.append(f"# {doc_request.title}")
        lines.append(f"*{doc_request.subtitle or 'Feature Implementation & Technical Documentation'}*\n")

        lines.append("## Document Metadata")
        lines.append(f"- **Author**: {doc_request.author}")
        lines.append(f"- **Ticket Key**: {doc_request.ticket_id or 'N/A'}")
        if doc_request.git_info:
            lines.append(f"- **Git Branch**: `{doc_request.git_info.branch_name}`")
            lines.append(f"- **Repository**: `{doc_request.git_info.repo_name}`")
        lines.append("")

        if doc_request.summary:
            lines.append("## Summary of Changes")
            lines.append(f"{doc_request.summary.overview}\n")
            
            if doc_request.summary.key_points:
                lines.append("### Key Highlights")
                for pt in doc_request.summary.key_points:
                    lines.append(f"- {pt}")
                lines.append("")

        if doc_request.git_info and doc_request.git_info.changed_files:
            lines.append("## Modified Files")
            for f in doc_request.git_info.changed_files:
                lines.append(f"- `{f}`")
            lines.append("")

        if doc_request.screenshots:
            lines.append("## Product Screenshots")
            for idx, shot in enumerate(doc_request.screenshots, 1):
                caption = shot.caption or f"Screenshot {idx}"
                lines.append(f"![{caption}]({shot.file_path})")
                lines.append(f"*{caption}*\n")

        if doc_request.git_info and doc_request.git_info.raw_diff:
            lines.append("## Code Diff Snippet")
            lines.append("```diff")
            lines.append(doc_request.git_info.raw_diff[:2000])
            lines.append("```\n")

        output_path = os.path.abspath(doc_request.output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return output_path
