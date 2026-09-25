"""Pure unit tests for guardrails.py - no HTTP, no MCP, no real time.sleep
(time is always passed in explicitly)."""

from automic_mcp.guardrails import Cooldown, TokenStore, matches_allowlist


class TestMatchesAllowlist:
    def test_exact_match(self) -> None:
        assert matches_allowlist("DAILY_BACKUP", ["DAILY_BACKUP"])

    def test_wildcard_match(self) -> None:
        assert matches_allowlist("TEST.JOBS.1", ["TEST.JOBS.*"])

    def test_no_match(self) -> None:
        assert not matches_allowlist("PROD.DELETE_ALL", ["TEST.JOBS.*"])

    def test_empty_allowlist_matches_nothing(self) -> None:
        assert not matches_allowlist("ANYTHING", [])

    def test_case_sensitive(self) -> None:
        # AE object names are conventionally uppercase; matching is
        # case-sensitive on purpose - no silent case-folding surprises.
        assert not matches_allowlist("daily_backup", ["DAILY_BACKUP"])


class TestTokenStore:
    def test_create_then_consume_returns_pending_execution(self) -> None:
        store = TokenStore()
        token = store.create("DAILY_BACKUP", {"x": "1"}, ttl_seconds=60, now=1000.0)

        pending = store.consume(token, now=1010.0)

        assert pending is not None
        assert pending.object_name == "DAILY_BACKUP"
        assert pending.inputs == {"x": "1"}

    def test_consume_unknown_token_returns_none(self) -> None:
        store = TokenStore()
        assert store.consume("nonexistent", now=1000.0) is None

    def test_token_is_single_use(self) -> None:
        store = TokenStore()
        token = store.create("DAILY_BACKUP", None, ttl_seconds=60, now=1000.0)

        first = store.consume(token, now=1001.0)
        second = store.consume(token, now=1002.0)

        assert first is not None
        assert second is None

    def test_expired_token_is_rejected(self) -> None:
        store = TokenStore()
        token = store.create("DAILY_BACKUP", None, ttl_seconds=60, now=1000.0)

        pending = store.consume(token, now=1061.0)  # 61s later - past the 60s TTL

        assert pending is None

    def test_token_valid_at_exact_ttl_boundary_is_expired(self) -> None:
        store = TokenStore()
        token = store.create("DAILY_BACKUP", None, ttl_seconds=60, now=1000.0)

        pending = store.consume(token, now=1060.0)  # exactly at expiry

        assert pending is None


class TestCooldown:
    def test_ready_before_any_execution(self) -> None:
        cooldown = Cooldown()
        assert cooldown.ready(now=1000.0, cooldown_seconds=5) is True

    def test_not_ready_immediately_after_success(self) -> None:
        cooldown = Cooldown()
        cooldown.record_success(now=1000.0)
        assert cooldown.ready(now=1002.0, cooldown_seconds=5) is False

    def test_ready_after_cooldown_elapses(self) -> None:
        cooldown = Cooldown()
        cooldown.record_success(now=1000.0)
        assert cooldown.ready(now=1006.0, cooldown_seconds=5) is True
