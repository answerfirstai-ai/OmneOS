"""Accept a public http URL. Credentials in the URL are rejected."""

from __future__ import annotations

from urllib.parse import urlparse

_UNSAFE = set("|&;<>`$()")
_CREDENTIAL = ("password", "passwd", "secret", "token", "cookie", "authorization")


def browser_url(value: str) -> str | None:
    """Return a public URL, or none when the value is not one."""

    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.username or parsed.password:
        return None
    if parsed.scheme == "about" and parsed.path == "blank" and not parsed.netloc:
        return "about:blank"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return candidate


def browser_query(value: str) -> str | None:
    """Return a research query, or none when it is empty or shell-like."""

    query = " ".join(value.split())
    if not query or len(query) > 200:
        return None
    if any(character in query for character in _UNSAFE):
        return None
    return query


def browser_target(value: str) -> str | None:
    """Return an automation target, or none when it names a credential."""

    target = " ".join(value.split())
    if not target or len(target) > 200:
        return None
    if any(character in target for character in _UNSAFE):
        return None
    lowered = target.casefold()
    if any(word in lowered for word in _CREDENTIAL):
        return None
    return target
