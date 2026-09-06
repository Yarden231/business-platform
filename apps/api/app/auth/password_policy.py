"""Enforcing the password policy.

`app.domain.passwords` decides *whether* a password is acceptable and stays
pure; this is the one place that turns its verdict into the API's error
envelope, so no caller has to assemble `details` itself and every rejection
looks the same whether it came from an HTTP request or the bootstrap CLI.

The rejected password never reaches the response: only the stable issue codes
do, which is the rule `docs/security.md` §5 sets for validation errors
generally and matters most here.
"""

from __future__ import annotations

from app.core.errors import ErrorDetail, PasswordInvalidError
from app.domain.passwords import password_policy_issues


def ensure_password_meets_policy(
    password: str,
    *,
    current_password: str | None = None,
    field: str | None = None,
) -> None:
    """Raise `PasswordInvalidError` unless `password` satisfies the policy.

    `field` names the request field the issues belong to, so an HTTP caller can
    attach the message to the right input. It is `None` for the CLI, which has
    no fields.
    """
    issues = password_policy_issues(password, current_password=current_password)
    if issues:
        raise PasswordInvalidError(
            details=[ErrorDetail(field=field, issue=issue.value) for issue in issues]
        )
