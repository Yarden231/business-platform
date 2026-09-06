"""Cross-cutting platform concerns: settings, logging, errors, request context, time.

Nothing in this package may import a web framework or the ORM; every other
layer is allowed to depend on it (see `docs/architecture.md` §4).
"""
