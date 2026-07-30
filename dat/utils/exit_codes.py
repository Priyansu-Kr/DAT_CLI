from enum import IntEnum

class ExitCode(IntEnum):
    SUCCESS = 0
    VALIDATION_ERROR = 1
    CONFIGURATION_ERROR = 2
    EXTERNAL_TOOL_ERROR = 3
    UNEXPECTED_ERROR = 4
