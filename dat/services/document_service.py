from typing import List, Optional
from dat.models.doc_request import DocRequest, ChangeSummary
from dat.models.screenshot_info import ScreenshotInfo
from dat.models.git_info import GitInfo
from dat.services.git_service import GitService
from dat.services.screenshot_service import ScreenshotService
from dat.services.ai_service import AIService
from dat.renderers.docx_renderer import DocxRenderer
from dat.renderers.markdown_renderer import MarkdownRenderer

class DocumentService:
    def __init__(
        self,
        git_service: Optional[GitService] = None,
        screenshot_service: Optional[ScreenshotService] = None,
        ai_service: Optional[AIService] = None,
        docx_renderer: Optional[DocxRenderer] = None,
        md_renderer: Optional[MarkdownRenderer] = None,
    ):
        self.git_service = git_service or GitService()
        self.screenshot_service = screenshot_service or ScreenshotService()
        self.ai_service = ai_service or AIService()
        self.docx_renderer = docx_renderer or DocxRenderer()
        self.md_renderer = md_renderer or MarkdownRenderer()

    def generate_documentation(
        self,
        output_path: Optional[str] = None,
        title_override: Optional[str] = None,
        author: str = "Developer",
        ticket_override: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        capture_adb: bool = False,
        output_format: str = "docx",
        cwd: Optional[str] = None,
    ) -> str:
        git_info = self.git_service.get_git_info(cwd=cwd)

        final_title = title_override or git_info.inferred_title
        final_ticket = ticket_override or git_info.ticket_id
        final_author = author
        if author == "Developer" and git_info.author_name:final_author = git_info.author_name

        # Generate output path from title if not provided
        if not output_path:
            # Match filename exactly to title as requested
            output_path = f"{final_title}.{output_format}"

        screenshots: List[ScreenshotInfo] = []
        if image_paths:
            screenshots.extend(self.screenshot_service.process_local_images(image_paths))

        if capture_adb:
            try:
                adb_shot = self.screenshot_service.capture_adb_screenshot()
                screenshots.append(adb_shot)
            except Exception as e:
                print(f"[Warning] ADB screenshot capture failed: {e}")

        summary = self.ai_service.generate_change_summary(git_info)

        doc_req = DocRequest(
            title=final_title,
            subtitle="Automated Feature Documentation",
            author=final_author,
            ticket_id=final_ticket,
            git_info=git_info,
            summary=summary,
            screenshots=screenshots,
            output_format=output_format,
            output_path=output_path,
        )

        if output_format.lower() == "md" or output_path.endswith(".md"):
            return self.md_renderer.render(doc_req)
        else:
            return self.docx_renderer.render(doc_req)
