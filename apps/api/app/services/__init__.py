"""Use cases: the transaction boundary, orchestration and audit emission.

A service method is the unit of work (`app.db.uow`). It is the only layer
allowed to commit, and every security-relevant mutation it makes lands in the
same transaction as the `activity_log` row describing it — so if the audit write
fails, the change it would have described is rolled back with it (ADR-0010).

Services are callable with no request in sight: they take plain values and an
`AuthenticatedActor`, never a FastAPI `Request`, which is what lets
`app.cli.create_admin` reuse the same code the routers call.
"""
