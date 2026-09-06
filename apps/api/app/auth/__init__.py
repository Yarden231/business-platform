"""Authentication: hashing, tokens, session handling, identity providers, policies.

The layer exists so that adding Microsoft Entra ID later is additive
(docs/architecture.md §6). It is split into the three pieces that change
independently:

* `hashing` and `tokens` — the cryptographic primitives, with no knowledge of
  users or requests;
* `provider` and `password_provider` — proving *who* somebody is, behind one
  protocol, so a second provider is a new module rather than an edit;
* `sessions` and `policies` — what happens *after* anybody authenticates, which
  is provider-independent and therefore written once.

Nothing here imports FastAPI: the same code path serves an HTTP login and the
admin-bootstrap CLI. Nothing here commits either — `app.services` owns the
transaction boundary (`app.db.uow`).
"""
