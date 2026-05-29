"""Compatibility wrapper for `csrcqsf.core.app`."""

import sys as _sys
from importlib import import_module as _import_module

_impl = _import_module("csrcqsf.core.app")
_sys.modules[__name__] = _impl
