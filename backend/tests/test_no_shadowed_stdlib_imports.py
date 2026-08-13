"""A local re-import of a module-level name silently breaks every earlier use of it.

Found in production. billing.py imports `datetime` at module level, and the Stripe
webhook handler re-imported it inside a nested branch. That makes `datetime` local to
the WHOLE function, so a use 31 lines earlier raised:

    cannot access local variable 'datetime' where it is not associated with a value

The handler catches everything and returns 200 — deliberately, so Stripe doesn't
retry forever — so Stripe recorded four successful deliveries while the customer's
trial-to-active conversion was never written to our database. The customer was
charged and the app kept asking them to choose a plan.

Nothing about this is visible in review: both imports are individually correct, the
crash needs one specific branch, and the symptom appears somewhere else entirely.
So it is checked structurally instead.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _python_files():
    for p in sorted(_BACKEND.rglob("*.py")):
        parts = set(p.parts)
        if parts & {"tests", "venv", ".venv", "alembic", "__pycache__"}:
            continue
        yield p


def _module_level_names(tree: ast.Module) -> set[str]:
    """Names bound by imports at module scope."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def _shadowing_imports(tree: ast.Module, module_names: set[str]):
    """(function, name, lineno) for local imports that actually break something.

    Rebinding a module-level name inside a function is only a bug when the name is
    also READ earlier in that function — that read hits the not-yet-assigned local
    and raises. A local import placed before every use is merely redundant, and the
    codebase does that deliberately in places to keep modules importable without a
    heavy dependency, so flagging it would be noise.
    """
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        reads: dict[str, int] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                prev = reads.get(node.id)
                if prev is None or node.lineno < prev:
                    reads[node.id] = node.lineno
        for node in ast.walk(fn):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if bound not in module_names:
                    continue
                first_read = reads.get(bound)
                if first_read is not None and first_read < node.lineno:
                    out.append((fn.name, bound, node.lineno))
    return out


@pytest.mark.parametrize("path", list(_python_files()), ids=lambda p: p.name)
def test_no_function_reimports_a_module_level_name(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module_names = _module_level_names(tree)
    offenders = _shadowing_imports(tree, module_names)
    assert not offenders, (
        f"{path.name}: these local imports rebind a name imported at module level, "
        "making it local to the whole function and breaking every earlier use:\n"
        + "\n".join(f"  {fn}() line {ln}: {name}" for fn, name, ln in offenders)
    )


def test_the_detector_catches_the_shape_that_shipped():
    """The exact billing.py pattern, so a rewrite of the check can't quietly stop
    catching it."""
    src = (
        "from datetime import datetime, timezone\n"
        "def handler(x):\n"
        "    if x:\n"
        "        a = datetime.now()\n"          # breaks
        "    if not x:\n"
        "        from datetime import datetime\n"  # makes it local for the whole fn
        "        b = datetime.now()\n"
    )
    tree = ast.parse(src)
    found = _shadowing_imports(tree, _module_level_names(tree))
    assert [(f, n) for f, n, _ in found] == [("handler", "datetime")]


def test_the_detector_allows_a_genuinely_local_import():
    """Lazy imports of things NOT imported at module level are the normal way to keep
    a module importable without a heavy dependency — those must stay allowed."""
    src = (
        "import os\n"
        "def handler():\n"
        "    import httpx\n"
        "    return httpx, os\n"
    )
    tree = ast.parse(src)
    assert _shadowing_imports(tree, _module_level_names(tree)) == []
