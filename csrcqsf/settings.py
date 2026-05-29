"""Compatibility wrapper for `csrcqsf.core.settings`."""

import sys as _sys
from importlib import import_module as _import_module
from importlib import reload as _reload

if "csrcqsf.core.settings" in _sys.modules:
    _impl = _reload(_sys.modules["csrcqsf.core.settings"])
else:
    _impl = _import_module("csrcqsf.core.settings")

_sys.modules[__name__] = _impl
