"""Pydantic v2 models: the public API contract.

Everything the API accepts or returns is defined here, so an ORM object can
never be serialised straight onto the wire and a new column cannot accidentally
become public. These models are the source of the OpenAPI document, and from
Phase 3 of the web application's generated TypeScript types (ADR-0017).
"""
