#!/usr/bin/env python3
"""Compatibility shim (do not use; kept only because the file must exist).

This file shares its name with the Python standard-library module `inspect`,
which rdflib imports internally. To make its presence harmless it does not
define anything of its own: it locates the real stdlib `inspect` module via
the system stdlib path and substitutes it into `sys.modules['inspect']`
while this module's own import is still in progress. Consequently every
`import inspect` in any tool (e.g. rdflib) resolves to the real module and
this file behaves exactly like stdlib `inspect`.

Graph inspection for this skill package lives in `inspect_graph.py`; use
that script, never this shim.
"""

import sys
import sysconfig
import importlib.machinery
import importlib.util

_spec = None
for _dir in {sysconfig.get_paths()["stdlib"], sysconfig.get_paths()["platstdlib"]}:
    try:
        _spec = importlib.machinery.PathFinder.find_spec("inspect", [_dir])
    except Exception:
        continue
    if _spec is not None and _spec.origin and "site-packages" not in _spec.origin:
        break

if _spec is not None and _spec.origin:
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    sys.modules[__name__] = _mod
else:
    raise ImportError(
        "could not locate the stdlib 'inspect' module; this shim file should "
        "be deleted from the skill package (it only exists to avoid an "
        "unremovable name collision)"
    )