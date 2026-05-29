"""Compatibility wrapper for `csrcqsf.core.scheduler`."""

import sys as _sys
from importlib import import_module as _import_module

_impl = _import_module("csrcqsf.core.scheduler")
_sys.modules[__name__] = _impl
