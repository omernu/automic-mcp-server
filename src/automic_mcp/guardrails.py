"""Pure, in-memory guardrail primitives for stage 4 (executing objects).

No HTTP, no MCP - kept testable without mocking anything. Time is always
passed in explicitly (as `now`, a time.time()-style float) rather than read
internally, so tests don't need to sleep or freeze the clock.
"""

import fnmatch
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


def matches_allowlist(object_name: str, patterns: Sequence[str]) -> bool:
    """True if object_name matches at least one allowlist pattern.

    Patterns use the same wildcards ('*', '?') as AE object name filters.
    An empty pattern list matches nothing - the allowlist must be
    explicitly populated, there's no "empty means allow all" default.
    """
    return any(fnmatch.fnmatchcase(object_name, pattern) for pattern in patterns)


@dataclass(frozen=True)
class PendingExecution:
    object_name: str
    inputs: dict[str, Any] | None
    expires_at: float


class TokenStore:
    """One-time confirmation tokens linking preview_execution to execute_object.

    A token is consumed (removed) the first time it's looked up, whether or
    not the caller goes on to actually execute anything - so a token can
    never be reused, and a denied/failed execute_object call still requires
    a fresh preview_execution before trying again.
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingExecution] = {}

    def create(
        self,
        object_name: str,
        inputs: dict[str, Any] | None,
        ttl_seconds: float,
        now: float,
    ) -> str:
        self._purge_expired(now)
        token = secrets.token_hex(8)
        self._pending[token] = PendingExecution(
            object_name=object_name, inputs=inputs, expires_at=now + ttl_seconds
        )
        return token

    def consume(self, token: str, now: float) -> PendingExecution | None:
        """Return and remove the pending execution for token, or None if the
        token is unknown or has expired."""
        self._purge_expired(now)
        return self._pending.pop(token, None)

    def _purge_expired(self, now: float) -> None:
        expired = [t for t, p in self._pending.items() if p.expires_at <= now]
        for t in expired:
            del self._pending[t]


class Cooldown:
    """Tracks a minimum gap between successful executions."""

    def __init__(self) -> None:
        self._last_success_at: float | None = None

    def ready(self, now: float, cooldown_seconds: float) -> bool:
        if self._last_success_at is None:
            return True
        return (now - self._last_success_at) >= cooldown_seconds

    def record_success(self, now: float) -> None:
        self._last_success_at = now
