from abc import ABC, abstractmethod
from dat.models.doc_request import DocRequest

class BaseRenderer(ABC):
    @abstractmethod
    def render(self, doc_request: DocRequest) -> str:
        pass
