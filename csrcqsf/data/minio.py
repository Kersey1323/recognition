"""Compatibility wrapper for `csrcqsf.infra.storage.minio`."""

import sys as _sys
from importlib import import_module as _import_module

_impl = _import_module("csrcqsf.infra.storage.minio")
_sys.modules[__name__] = _impl
