"""Write the OpenAPI document to stdout.

    ./scripts/generate-api-types          # regenerate the web client's types
    uv run python -m app.cli.dump_openapi # just the document

The web application's request and response types are generated from this
document rather than hand-written (ADR-0017), and `./scripts/check` fails if the
committed types no longer match it.

The document is built from the application object in this process, not fetched
from a running server. A generation step that needs a live API and a reachable
database would be a step CI could only run after starting the stack, and the
document does not depend on either: it is a function of the route decorators and
the Pydantic models. `create_app()` never opens a connection — that happens in
`lifespan`, which is not entered here.

Interactive documentation is disabled under `APP_ENV=production`
(docs/security.md §8), which is a question of what the *server publishes*.
`app.openapi()` is unaffected, so the types can be regenerated from a
production-configured checkout as well.
"""

from __future__ import annotations

import json
import sys

from app.main import create_app


def main() -> int:
    """Serialise the OpenAPI document. Sorted keys, so the output is stable."""
    document = create_app().openapi()
    json.dump(document, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
