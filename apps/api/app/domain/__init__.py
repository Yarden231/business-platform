"""Pure business vocabulary and logic.

Nothing here may import SQLAlchemy, FastAPI or any other framework, which is
enforced by an import-linter contract. That constraint is the point: the status
graph, the Israeli ID checksum and the case-number formatter arriving in later
phases are unit-testable without a database or an HTTP client.
"""
