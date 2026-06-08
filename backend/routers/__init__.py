"""Domain routers mounted onto the app in main.py.

Each module defines a module-level ``router = APIRouter()``. main.py imports the
module and calls ``app.include_router(<module>.router)``. Routers never import
``main`` — they depend only on leaf modules (database, runtime, deps, models,
settings, ...), which keeps the import graph acyclic.
"""
