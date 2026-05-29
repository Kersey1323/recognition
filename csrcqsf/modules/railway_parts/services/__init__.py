"""Railway parts business service implementations."""

from importlib import import_module

__all__ = [
    "parts_service",
    "parts_search_service",
    "reconstruction_service",
    "reconstruction_task_service",
    "reconstruction_video_service",
]


def __getattr__(name: str):
    if name in __all__:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
