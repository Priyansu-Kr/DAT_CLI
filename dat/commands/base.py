from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dat.utils.exit_codes import ExitCode
from dat.utils.container import Container

class BaseCommand(ABC):
    def __init__(self, container: Optional[Container] = None):
        self.container = container or Container.get_instance()

    @abstractmethod
    def execute(self, args: Dict[str, Any]) -> ExitCode:
        pass
