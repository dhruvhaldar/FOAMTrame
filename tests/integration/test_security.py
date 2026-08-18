from __future__ import annotations

from flask import Flask, jsonify
import pytest

from security import (
    API_KEY_HEADER,
    apply_trame_security,
    configure_flask_security,
    default_security_preferences,
    hash_api_key,
    normalise_security_preferences,
    trame_session_timeout_seconds,
    verify_api_key,
)


def make_app(preferences):
    app = Flask(__name__)
    configure_flask_security(app, lambda: preferences)

    @app.get("/probe")
    def probe():
        return jsonify({"ok": True})

    @app.post("/mutate")
    def mutate():
        return jsonify({"ok": True})

    return app


def enabled_preferences(**updates):
    preferences = default_security_preferences()
    preferences.update({"security_enabled": True, **updates})
    return normalise_security_preferences(preferences)


def test_optional_security_is_disabled_by_default():
    preferences = default_security_preferences()
    assert preferences["security_enabled"] is False
    assert preferences["session_timeout_enabled"] is False
    assert trame_session_timeout_seconds(preferences) == 0

    response = (
        make_app(preferences)
        .test_client()
        .get("/probe", headers={"Origin": "https://untrusted.example"})
    )
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "X-Frame-Options" not in response.headers


def test_same_origin_policy_rejects_cross_origin_browser_requests():
    app = make_app(enabled_preferences())
    client = app.test_client()

    allowed = client.get("/probe", headers={"Origin": "http://localhost"})
    rejected = client.get("/probe", headers={"Origin": "https://evil.example"})

    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost"
    assert allowed.headers["X-Content-Type-Options"] == "nosniff"
    assert rejected.status_code == 403


def test_trusted_origin_and_any_origin_cors_headers():
    trusted_preferences = enabled_preferences(
        cors_mode="trusted_origin", cors_origin="https://ui.example"
    )
    trusted = (
        make_app(trusted_preferences)
        .test_client()
        .get("/probe", headers={"Origin": "https://ui.example"})
    )
    assert trusted.headers["Access-Control-Allow-Origin"] == "https://ui.example"

    any_preferences = enabled_preferences(cors_mode="any")
    public = (
        make_app(any_preferences)
        .test_client()
        .get("/probe", headers={"Origin": "https://any.example"})
    )
    assert public.headers["Access-Control-Allow-Origin"] == "*"


def test_api_key_protects_mutating_companion_api_requests():
    secret = "a-secure-api-key-value"
    preferences = default_security_preferences()
    preferences.update(
        {
            "security_enabled": True,
            "api_key_enabled": True,
            "api_key_hash": hash_api_key(secret, salt=b"0123456789abcdef"),
        }
    )
    client = make_app(preferences).test_client()

    assert client.post("/mutate").status_code == 401
    assert client.post("/mutate", headers={API_KEY_HEADER: secret}).status_code == 200
    assert verify_api_key(secret, preferences["api_key_hash"])
    assert not verify_api_key("incorrect", preferences["api_key_hash"])


def test_request_size_limit_is_enforced_before_route_execution():
    preferences = default_security_preferences()
    preferences["security_enabled"] = True
    preferences["max_request_mb"] = 1
    client = make_app(preferences).test_client()

    response = client.post(
        "/mutate",
        data=b"x" * (1024 * 1024 + 1),
        content_type="application/octet-stream",
    )
    assert response.status_code == 413


def test_security_preferences_validate_origins_and_limits():
    with pytest.raises(ValueError, match=r"http\(s\) origin"):
        normalise_security_preferences(
            {"cors_mode": "trusted_origin", "cors_origin": "javascript:alert(1)"}
        )
    with pytest.raises(ValueError, match="between 1 and 64"):
        normalise_security_preferences({"websocket_max_message_mb": 65})
    with pytest.raises(ValueError, match="between 1 and 1440"):
        normalise_security_preferences({"session_timeout_minutes": 0})
    with pytest.raises(ValueError, match="API-key hash is invalid"):
        normalise_security_preferences(
            {
                "api_key_enabled": True,
                "api_key_hash": "pbkdf2_sha256$999999999$00$00",
            }
        )
    assert not verify_api_key("irrelevant", "pbkdf2_sha256$999999999$00$00")


def test_session_timeout_requires_both_security_and_its_own_switch():
    preferences = default_security_preferences()
    preferences.update({"session_timeout_enabled": True, "session_timeout_minutes": 45})
    assert trame_session_timeout_seconds(preferences) == 0

    preferences["security_enabled"] = True
    assert trame_session_timeout_seconds(preferences) == 45 * 60


def test_trame_headers_and_bind_mode_are_applied(monkeypatch):
    class FakeHeaders:
        def __init__(self):
            self.values = {}

        def set_header(self, key, value):
            self.values[key] = value

        def remove_header(self, key):
            self.values.pop(key, None)

    class FakeServer:
        http_headers = FakeHeaders()

    preferences = normalise_security_preferences(
        {
            "security_enabled": True,
            "cors_mode": "trusted_origin",
            "cors_origin": "https://ui.example",
            "websocket_max_message_mb": 8,
        }
    )
    monkeypatch.delenv("WSLINK_MAX_MSG_SIZE", raising=False)
    server = FakeServer()
    apply_trame_security(server, preferences)

    assert server.http_headers.values["Access-Control-Allow-Origin"] == (
        "https://ui.example"
    )
    assert server.http_headers.values["X-Frame-Options"] == "DENY"
    assert int(__import__("os").environ["WSLINK_MAX_MSG_SIZE"]) == 8 * 1024 * 1024
