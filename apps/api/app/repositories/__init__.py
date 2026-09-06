"""Query and persistence encapsulation.

Repositories own SQL and nothing else: no transactions, no audit, no policy.
They are the layer that later gets the actor-scoped query methods employee
visibility depends on (ADR-0013), which is why they exist as their own layer
rather than as helper functions on the services.

Nothing here commits. The service that called a repository owns the transaction
(`app.db.uow`).
"""
