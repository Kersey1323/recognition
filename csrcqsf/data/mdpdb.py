"""Compatibility wrapper for `csrcqsf.infra.db.mdp_db`."""

import sys as _sys
from importlib import import_module as _import_module

_impl = _import_module("csrcqsf.infra.db.mdp_db")
_sys.modules[__name__] = _impl
