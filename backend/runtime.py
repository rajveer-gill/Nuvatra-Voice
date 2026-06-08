"""Mutable process-wide runtime state, owned in one place.

Several values are decided at startup and then read from many call sites — most
importantly ``USE_DB`` (flipped on once the database connects). When the codebase
lived in a single ``main.py`` module these could be plain module globals. As the
app is split into routers, those routers must read the *live* value, so the state
lives here and is always accessed by attribute on the module:

    import runtime
    if runtime.USE_DB:
        ...

NEVER ``from runtime import USE_DB`` — that binds a one-time snapshot of the bool
and would silently miss the startup flip. Tests patch ``runtime.USE_DB``.
"""

from __future__ import annotations

# True once init_db() has successfully connected. Written by the startup paths in
# main.py (init_db_background / _ensure_db_ready); read across the app.
USE_DB: bool = False
