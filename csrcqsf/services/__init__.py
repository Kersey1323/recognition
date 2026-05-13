__all__ = [
    "parts_router",
    "image_router",
    "sgo_router",
    "parts_docs_router",
]


def __getattr__(name):
    if name == "parts_router":
        from .parts import parts_router

        return parts_router
    if name == "image_router":
        from .images import image_router

        return image_router
    if name == "sgo_router":
        from .sgo import sgo_router

        return sgo_router
    if name == "parts_docs_router":
        from .doc_parse import parts_docs_router

        return parts_docs_router
    raise AttributeError(name)
