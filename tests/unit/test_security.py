"""Testy bezpečnostní vrstvy - základ bezpečnosti je v kódu, ne v modelu."""

from __future__ import annotations

from martin.security.audit import AuditLog
from martin.security.engine import PolicyEngine, ToolRegistry
from martin.security.policy import PolicyOutcome, SecurityLevel
from martin.security.redaction import contains_secret, redact_secrets


class TestSecurityLevels:
    def test_safe_tool_is_allowed(self, registry, policy):
        registry.register(
            "read_thing", "Přečte věc.", SecurityLevel.SAFE, lambda: {"ok": True}
        )
        decision = policy.evaluate("read_thing")
        assert decision.allowed
        assert decision.level is SecurityLevel.SAFE

    def test_confirm_tool_requires_approval(self, registry, policy):
        registry.register(
            "write_thing", "Zapíše věc.", SecurityLevel.CONFIRM, lambda: {"ok": True}
        )
        decision = policy.evaluate("write_thing")
        assert decision.needs_confirmation
        assert not decision.allowed

    def test_block_tool_is_always_denied(self, registry, policy):
        registry.register(
            "danger", "Nebezpečná věc.", SecurityLevel.BLOCK, lambda: {"ok": True}
        )
        decision = policy.evaluate("danger")
        assert decision.denied

    def test_block_tool_never_executes(self, registry, policy):
        called = {"value": False}

        def handler():
            called["value"] = True
            return {"ok": True}

        registry.register("danger", "Nebezpečná.", SecurityLevel.BLOCK, handler)
        decision, result = policy.execute("danger")
        assert decision.denied
        assert result is None
        assert called["value"] is False

    def test_unknown_tool_is_denied(self, policy):
        decision = policy.evaluate("tajny_tool")
        assert decision.denied
        assert "registrován" in decision.reason

    def test_approval_unblocks_confirm_tool(self, registry, policy):
        registry.register(
            "write_thing", "Zapíše věc.", SecurityLevel.CONFIRM, lambda: {"ok": True}
        )
        policy.approve("write_thing")
        decision = policy.evaluate("write_thing")
        assert decision.allowed


class TestValidators:
    def test_validator_blocks_bad_args(self, registry, policy):
        def validator(args):
            if args.get("value", 0) > 10:
                return "Hodnota je příliš velká."
            return None

        registry.register(
            "set_value",
            "Nastaví hodnotu.",
            SecurityLevel.SAFE,
            lambda value: {"ok": True},
            validator=validator,
        )
        decision = policy.evaluate("set_value", {"value": 99})
        assert decision.denied
        assert "příliš velká" in decision.reason

    def test_validator_passes_good_args(self, registry, policy):
        registry.register(
            "set_value",
            "Nastaví hodnotu.",
            SecurityLevel.SAFE,
            lambda value: {"ok": True, "value": value},
            validator=lambda args: None if args.get("value", 0) <= 10 else "too big",
        )
        decision, result = policy.execute("set_value", {"value": 5})
        assert decision.allowed
        assert result == {"ok": True, "value": 5}

    def test_validator_exception_denies(self, registry, policy):
        def broken_validator(args):
            raise RuntimeError("validator spadl")

        registry.register(
            "thing", "Věc.", SecurityLevel.SAFE, lambda: {"ok": True},
            validator=broken_validator,
        )
        decision = policy.evaluate("thing")
        assert decision.denied
        assert "selhala" in decision.reason


class TestHandlerErrors:
    def test_handler_exception_is_captured(self, registry, policy):
        def boom():
            raise RuntimeError("selhání")

        registry.register("boom", "Věc.", SecurityLevel.SAFE, boom)
        decision, result = policy.execute("boom")
        assert decision.allowed
        assert "error" in result

    def test_wrong_arguments_do_not_crash(self, registry, policy):
        registry.register(
            "thing", "Věc.", SecurityLevel.SAFE, lambda value: {"ok": value}
        )
        decision, result = policy.execute("thing", {"wrong": 1})
        assert decision.allowed
        assert "error" in result


class TestAuditLog:
    def test_audit_records_decisions(self, registry, policy, audit_log):
        registry.register(
            "read_thing", "Přečte věc.", SecurityLevel.SAFE, lambda: {"ok": True}
        )
        policy.evaluate("read_thing")
        events = audit_log.events()
        assert len(events) == 1
        assert events[0].tool == "read_thing"
        assert events[0].outcome == "allow"

    def test_audit_writes_to_disk(self, registry, policy, audit_log):
        registry.register(
            "read_thing", "Přečte věc.", SecurityLevel.SAFE, lambda: {"ok": True}
        )
        policy.evaluate("read_thing")
        assert audit_log.path.is_file()
        loaded = audit_log.load()
        assert len(loaded) == 1
        assert loaded[0]["tool"] == "read_thing"

    def test_audit_does_not_store_secrets(self, registry, policy, audit_log):
        registry.register(
            "login", "Přihlášení.", SecurityLevel.SAFE, lambda password: {"ok": True}
        )
        policy.evaluate("login", {"password": "tajne-heslo-123", "user": "lukas"})
        raw = audit_log.path.read_text(encoding="utf-8")
        assert "tajne-heslo-123" not in raw
        assert "tajne" not in raw


class TestRedaction:
    def test_redacts_sensitive_keys(self):
        result = redact_secrets(
            {"password": "hunter2", "api_key": "abc", "path": "C:/ok"}
        )
        assert result["password"] == "[REDACTED]"
        assert result["api_key"] == "[REDACTED]"
        assert result["path"] == "C:/ok"

    def test_redacts_nested(self):
        result = redact_secrets({"outer": {"secret": "xyz"}})
        assert result["outer"]["secret"] == "[REDACTED]"

    def test_redacts_text_patterns(self):
        assert "[REDACTED]" in redact_secrets("password=mysecret")
        assert "[REDACTED]" in redact_secrets("Authorization: Bearer abc123")
        assert "[REDACTED]" in redact_secrets('{"token": "abc"}')

    def test_contains_secret(self):
        assert contains_secret("password=abc")
        assert not contains_secret("just a normal sentence")