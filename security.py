from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Mapping
from urllib.parse import urlsplit

PBKDF2_ITERATIONS = 310_000
API_KEY_HEADER = "X-FOAMTrame-API-Key"


def default_security_preferences() -> dict[str, Any]:
    return {
        "security_enabled": False,
        "bind_mode": "loopback",
        "cors_mode": "same_origin",
        "cors_origin": "",
        "security_headers": True,
        "api_key_enabled": False,
        "api_key_hash": "",
        "max_request_mb": 2,
        "websocket_max_message_mb": 4,
        "session_timeout_enabled": False,
        "session_timeout_minutes": 30,
    }


def validate_origin(value: str) -> str:
    origin = str(value or "").strip().rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "Trusted origin must be an http(s) origin such as https://example.com."
        )
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return parsed


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def normalise_security_preferences(data: Any) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        data = {}
    preferences = default_security_preferences()
    preferences.update({key: data[key] for key in preferences if key in data})

    if preferences["bind_mode"] not in {"loopback", "network"}:
        preferences["bind_mode"] = "loopback"
    if preferences["cors_mode"] not in {"same_origin", "trusted_origin", "any"}:
        preferences["cors_mode"] = "same_origin"

    preferences["security_headers"] = _as_bool(preferences["security_headers"])
    preferences["security_enabled"] = _as_bool(preferences["security_enabled"])
    preferences["api_key_enabled"] = _as_bool(preferences["api_key_enabled"])
    preferences["api_key_hash"] = str(preferences["api_key_hash"] or "")
    preferences["max_request_mb"] = _bounded_int(
        preferences["max_request_mb"], "Maximum API request size", 1, 64
    )
    preferences["websocket_max_message_mb"] = _bounded_int(
        preferences["websocket_max_message_mb"],
        "Maximum WebSocket message size",
        1,
        64,
    )
    preferences["session_timeout_enabled"] = _as_bool(
        preferences["session_timeout_enabled"]
    )
    preferences["session_timeout_minutes"] = _bounded_int(
        preferences["session_timeout_minutes"],
        "Session timeout",
        1,
        1440,
    )

    if preferences["cors_mode"] == "trusted_origin":
        preferences["cors_origin"] = validate_origin(preferences["cors_origin"])
    else:
        preferences["cors_origin"] = ""
    if preferences["api_key_enabled"] and not preferences["api_key_hash"]:
        raise ValueError("Set an API key before enabling API-key protection.")
    if preferences["api_key_hash"] and not valid_api_key_hash(
        preferences["api_key_hash"]
    ):
        raise ValueError("The stored API-key hash is invalid.")
    return preferences


def hash_api_key(api_key: str, *, salt: bytes | None = None) -> str:
    secret = str(api_key or "")
    if len(secret) < 16:
        raise ValueError("API key must contain at least 16 characters.")
    actual_salt = os.urandom(16) if salt is None else salt
    digest = hashlib.pbkdf2_hmac(
        "sha256", secret.encode("utf-8"), actual_salt, PBKDF2_ITERATIONS
    )
    return (
        f"pbkdf2_sha256${PBKDF2_ITERATIONS}$"
        f"{actual_salt.hex()}${digest.hex()}"
    )


def valid_api_key_hash(encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = str(encoded).split("$", 3)
        return (
            algorithm == "pbkdf2_sha256"
            and int(iterations) == PBKDF2_ITERATIONS
            and len(bytes.fromhex(salt_hex)) == 16
            and len(bytes.fromhex(digest_hex)) == 32
        )
    except (TypeError, ValueError):
        return False


def verify_api_key(api_key: str, encoded: str) -> bool:
    try:
        if not valid_api_key_hash(encoded):
            return False
        algorithm, iterations, salt_hex, expected_hex = str(encoded).split("$", 3)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            str(api_key or "").encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), expected_hex)
    except (TypeError, ValueError):
        return False


def origin_allowed(
    request_origin: str | None,
    host_origin: str,
    preferences: Mapping[str, Any],
) -> bool:
    if not request_origin:
        return True
    origin = str(request_origin).strip().rstrip("/").lower()
    mode = preferences.get("cors_mode", "same_origin")
    if mode == "any":
        return True
    if mode == "trusted_origin":
        return origin == str(preferences.get("cors_origin", "")).lower()
    return origin == str(host_origin).strip().rstrip("/").lower()


def cors_response_origin(
    request_origin: str | None,
    host_origin: str,
    preferences: Mapping[str, Any],
) -> str | None:
    if not request_origin or not origin_allowed(request_origin, host_origin, preferences):
        return None
    return "*" if preferences.get("cors_mode") == "any" else request_origin


def apply_trame_security(server, preferences: Mapping[str, Any]) -> None:
    """Apply startup-time policies supported by Trame's aiohttp backend."""
    headers = server.http_headers
    for name in (
        "Access-Control-Allow-Origin",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
    ):
        headers.remove_header(name)

    if not preferences.get("security_enabled", False):
        return

    if preferences.get("security_headers", True):
        headers.set_header("X-Content-Type-Options", "nosniff")
        headers.set_header("X-Frame-Options", "DENY")
        headers.set_header("Referrer-Policy", "no-referrer")
        headers.set_header(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )

    cors_mode = preferences.get("cors_mode", "same_origin")
    if cors_mode == "any":
        headers.set_header("Access-Control-Allow-Origin", "*")
    elif cors_mode == "trusted_origin":
        headers.set_header(
            "Access-Control-Allow-Origin", str(preferences.get("cors_origin", ""))
        )

    os.environ["WSLINK_MAX_MSG_SIZE"] = str(
        int(preferences.get("websocket_max_message_mb", 4)) * 1024 * 1024
    )


def trame_bind_host(preferences: Mapping[str, Any]) -> str:
    if not preferences.get("security_enabled", False):
        return "127.0.0.1"
    return "0.0.0.0" if preferences.get("bind_mode") == "network" else "127.0.0.1"


def trame_session_timeout_seconds(preferences: Mapping[str, Any]) -> int:
    """Return Trame's no-client shutdown delay, or zero when disabled."""
    if not preferences.get("security_enabled", False):
        return 0
    if not preferences.get("session_timeout_enabled", False):
        return 0
    return int(preferences.get("session_timeout_minutes", 30)) * 60


def configure_flask_security(app, preferences_loader) -> None:
    """Install origin, request-size, API-key, and response-header policies."""
    from flask import jsonify, request

    initial = preferences_loader()
    app.config["MAX_CONTENT_LENGTH"] = (
        int(initial["max_request_mb"]) * 1024 * 1024
        if initial.get("security_enabled", False)
        else None
    )

    def request_host_origin() -> str:
        return f"{request.scheme}://{request.host}"

    @app.before_request
    def enforce_optional_security():
        preferences = preferences_loader()
        if not preferences.get("security_enabled", False):
            app.config["MAX_CONTENT_LENGTH"] = None
            return None
        request_origin = request.headers.get("Origin")
        if not origin_allowed(request_origin, request_host_origin(), preferences):
            return jsonify({"error": "Origin is not allowed by the CORS policy."}), 403

        max_bytes = int(preferences["max_request_mb"]) * 1024 * 1024
        app.config["MAX_CONTENT_LENGTH"] = max_bytes
        if request.content_length is not None and request.content_length > max_bytes:
            return jsonify({"error": "Request body exceeds the configured limit."}), 413

        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and preferences.get("api_key_enabled")
            and not verify_api_key(
                request.headers.get(API_KEY_HEADER, ""),
                preferences.get("api_key_hash", ""),
            )
        ):
            return jsonify(
                {"error": f"A valid {API_KEY_HEADER} header is required."}
            ), 401
        return None

    @app.after_request
    def apply_optional_security_headers(response):
        preferences = preferences_loader()
        if not preferences.get("security_enabled", False):
            return response
        if preferences.get("security_headers", True):
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "no-referrer")
            response.headers.setdefault(
                "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
            )

        allowed_origin = cors_response_origin(
            request.headers.get("Origin"), request_host_origin(), preferences
        )
        if allowed_origin:
            response.headers["Access-Control-Allow-Origin"] = allowed_origin
            response.headers.add("Vary", "Origin")
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, HEAD, POST, OPTIONS"
            )
            response.headers["Access-Control-Allow-Headers"] = (
                f"Content-Type, {API_KEY_HEADER}"
            )
            response.headers["Access-Control-Max-Age"] = "600"
        return response
