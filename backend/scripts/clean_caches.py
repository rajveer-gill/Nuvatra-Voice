#!/usr/bin/env python3
"""Remove Python and pytest caches under backend. Run from project root: python backend/scripts/clean_caches.py"""
from pathlib import Path
import shutil

backend = Path(__file__).resolve().parent.parent
removed = []
for pycache in backend.rglob("__pycache__"):
    if pycache.is_dir():
        shutil.rmtree(pycache, ignore_errors=True)
        removed.append(str(pycache.relative_to(backend)))
pytest_cache = backend / ".pytest_cache"
if pytest_cache.is_dir():
    shutil.rmtree(pytest_cache, ignore_errors=True)
    removed.append(".pytest_cache")
print("Cleaned:", removed if removed else "(already clean)")
