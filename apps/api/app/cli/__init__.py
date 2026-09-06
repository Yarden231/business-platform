"""Operator commands.

Thin argument-parsing and prompting shells over `app.services`, so an
administrative action taken at a terminal goes through the same validation,
hashing, transaction boundary and audit trail as one taken over HTTP. The rule
this package exists to keep is that nothing here contains business logic or SQL
of its own.
"""
