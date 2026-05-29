"""Compatibility wrapper for `csrcqsf.infra.vector_store.milvus`."""

import sys as _sys
from importlib import import_module as _import_module

_impl = _import_module("csrcqsf.infra.vector_store.milvus")
_sys.modules[__name__] = _impl
