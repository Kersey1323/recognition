"""Compatibility wrapper for `csrcqsf.infra.external.model_client`."""

import sys as _sys
from importlib import import_module as _import_module

_impl = _import_module("csrcqsf.infra.external.model_client")
_sys.modules[__name__] = _impl
