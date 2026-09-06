"""Database infrastructure: metadata, engine, session lifecycle, transactions.

This package knows how to talk to PostgreSQL. It knows nothing about the tables
themselves — those are `app.models`, which import `Base` from here.
"""
