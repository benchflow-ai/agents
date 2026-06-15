"""Install-time overlay deployed into the host Omnigent's site-packages.

These modules are NOT imported by this package at runtime — they are read as
source and base64-deployed into the installed Omnigent under
``omnigent/inner/`` by :func:`omnigent.register.register_mimo`'s install
command, where they import real Omnigent internals (``omnigent.inner.executor``,
``omnigent.runtime.harnesses._executor_adapter``, ``fastapi``).

Only :mod:`omnigent.overlay._mimo_acp` is dependency-free and therefore both
deployed AND unit-tested here. :mod:`mimo_executor` and :mod:`mimo_harness`
import Omnigent internals, so they are verified by content assertions + the live
in-sandbox run, not by import in this package's test environment.
"""
