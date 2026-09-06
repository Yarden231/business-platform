"""The HTTP layer: routers, dependencies, middleware and exception handlers.

Nothing here contains a business rule or a query. Routers validate input,
resolve dependencies, call one service method and return a typed response
model. An import-linter contract stops this package from reaching the ORM
models directly.
"""
