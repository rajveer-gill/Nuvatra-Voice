"""Guard against the bug class that took the dashboard down: a bare name used in a
router/service module that is never imported or defined there. Python only raises the
NameError when that line executes, so import-smoke and under-tested endpoints miss it
(that's exactly how `verify_clerk_token` reached prod in routers/admin.py).

This is a conservative static scan, not a full linter: it flags a Load-context name
only when it is bound NOWHERE in the module (no import, def/class, assignment, param,
lambda arg, comprehension/except target, or global/nonlocal). That under-reports
scope-leak bugs but has near-zero false positives. Modules with `import *` are skipped
(can't reason about their namespace). If this ever false-positives on valid code, prefer
adding the missing binding; only relax the scan as a last resort.
"""

from __future__ import annotations

import ast
import builtins
import glob
import os

_BUILTINS = set(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__package__", "__class__", "self", "cls",
}

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bound_names(tree: ast.AST) -> set:
    """Every name bound anywhere in the module's source."""
    names: set = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                names.add("*STAR*" if a.name == "*" else (a.asname or a.name))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = n.args
            for arg in a.posonlyargs + a.args + a.kwonlyargs:
                names.add(arg.arg)
            if a.vararg:
                names.add(a.vararg.arg)
            if a.kwarg:
                names.add(a.kwarg.arg)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            names.add(n.id)
        if isinstance(n, (ast.Global, ast.Nonlocal)):
            names.update(n.names)
        if isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
    return names


def _undefined_in(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    bound = _bound_names(tree)
    if "*STAR*" in bound:
        return []  # star import: namespace is opaque, skip
    defined = bound | _BUILTINS
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in defined:
            bad.append((n.lineno, n.id))
    return bad


def test_routers_have_no_undefined_names():
    offenders = {}
    for path in sorted(glob.glob(os.path.join(_HERE, "routers", "*.py"))):
        bad = _undefined_in(path)
        if bad:
            offenders[os.path.relpath(path, _HERE)] = bad
    assert not offenders, "Undefined names (likely missing import/qualification): " + str(offenders)
