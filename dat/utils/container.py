from typing import Optional
from dat.adapters.filesystem_adapter import FilesystemAdapter
from dat.adapters.git_adapter import GitAdapter
from dat.adapters.adb_adapter import ADBAdapter
from dat.adapters.ai_adapter import AIAdapter
from dat.renderers.docx_renderer import DocxRenderer
from dat.renderers.markdown_renderer import MarkdownRenderer
from dat.services.configuration_service import ConfigurationService
from dat.services.git_service import GitService
from dat.services.screenshot_service import ScreenshotService
from dat.services.ai_service import AIService
from dat.services.document_service import DocumentService

class Container:
    _instance: Optional['Container'] = None

    def __init__(self):
        self.filesystem_adapter = FilesystemAdapter()
        self.configuration_service = ConfigurationService(fs=self.filesystem_adapter)
        self.config = self.configuration_service.load_config()

        self.git_adapter = GitAdapter(git_path=self.config.git_path)
        self.adb_adapter = ADBAdapter(adb_path=self.config.adb_path)
        self.ai_adapter = AIAdapter(provider=self.config.ai_provider, api_key=self.config.ai_api_key)

        self.docx_renderer = DocxRenderer()
        self.md_renderer = MarkdownRenderer()

        self.git_service = GitService(git_adapter=self.git_adapter)
        self.screenshot_service = ScreenshotService(adb_adapter=self.adb_adapter, fs_adapter=self.filesystem_adapter)
        self.ai_service = AIService(ai_adapter=self.ai_adapter)

        self.document_service = DocumentService(
            git_service=self.git_service,
            screenshot_service=self.screenshot_service,
            ai_service=self.ai_service,
            docx_renderer=self.docx_renderer,
            md_renderer=self.md_renderer,
        )

    @classmethod
    def get_instance(cls) -> 'Container':
        if cls._instance is None:
            cls._instance = Container()
        return cls._instance
