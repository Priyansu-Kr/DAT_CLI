"""Shared utilities.

The convenience re-exports below are resolved lazily (PEP 562). Importing
them eagerly pulled `Container` - and through it every adapter, renderer and
service - into scope the moment *any* module under `dat.utils` was imported,
so a util that an adapter needed created a circular import.
"""
from typing import Any

__all__ = ["ExitCode", "Container"]


def __getattr__(name: str) -> Any:
    if name == "ExitCode":
        from dat.utils.exit_codes import ExitCode
        return ExitCode
    if name == "Container":
        from dat.utils.container import Container
        return Container
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
