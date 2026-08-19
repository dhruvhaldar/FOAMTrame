from __future__ import annotations

import base64
import json
import secrets
from typing import Any

from trame.widgets import client, html, vuetify

from app_state import (
    export_app_state_json,
    load_security_preferences,
    restore_app_state_json,
    update_security_preferences,
)
from security import hash_api_key, normalise_security_preferences

MAX_APP_STATE_UPLOAD_BYTES = 2 * 1024 * 1024


def _uploaded_bytes(file_value: Any) -> tuple[str, bytes]:
    item = file_value
    if isinstance(file_value, (list, tuple)) and file_value:
        item = file_value[0]

    name = "app_state.json"
    content = None
    if isinstance(item, dict):
        name = item.get("name") or item.get("filename") or name
        content = item.get("content")
    elif hasattr(item, "name") or hasattr(item, "content"):
        name = getattr(item, "name", None) or getattr(item, "filename", None) or name
        content = getattr(item, "content", None)
    elif isinstance(item, (bytes, bytearray, memoryview, str)):
        content = item

    if content is None:
        raise ValueError("The selected file did not contain readable data.")
    if isinstance(content, memoryview):
        content = content.tobytes()
    if isinstance(content, bytearray):
        content = bytes(content)
    if isinstance(content, bytes):
        return name, content
    if isinstance(content, str):
        encoded = content.split(",", 1)[-1] if content.startswith("data:") else content
        try:
            # Trame transports uploads as Base64; this is not encryption.
            return name, base64.b64decode(encoded, validate=True)  # nosec
        except Exception:
            return name, content.encode("utf-8")
    if isinstance(content, (list, tuple)):
        return name, bytes(content)
    raise ValueError("Unsupported app-state upload format.")


def setup_settings_tab(server):
    state, ctrl = server.state, server.controller

    state.setdefault("app_state_backup_json", export_app_state_json())
    state.setdefault("app_state_restore_upload", None)
    state.setdefault("app_state_restore_pending", "")
    state.setdefault("app_state_restore_name", "")
    state.setdefault("app_state_settings_status", "Your app state is ready to back up.")
    state.setdefault("app_state_settings_status_color", "info")
    security_preferences = load_security_preferences()
    state.setdefault("security_enabled", security_preferences["security_enabled"])
    state.setdefault(
        "security_allow_network", security_preferences["bind_mode"] == "network"
    )
    state.setdefault("security_cors_mode", security_preferences["cors_mode"])
    state.setdefault("security_cors_origin", security_preferences["cors_origin"])
    state.setdefault(
        "security_headers_enabled", security_preferences["security_headers"]
    )
    state.setdefault(
        "security_api_key_enabled", security_preferences["api_key_enabled"]
    )
    state.setdefault(
        "security_api_key_configured", bool(security_preferences["api_key_hash"])
    )
    state.setdefault("security_api_key_new", "")
    state.setdefault("security_max_request_mb", security_preferences["max_request_mb"])
    state.setdefault(
        "security_websocket_max_message_mb",
        security_preferences["websocket_max_message_mb"],
    )
    state.setdefault(
        "security_session_timeout_enabled",
        security_preferences["session_timeout_enabled"],
    )
    state.setdefault(
        "security_session_timeout_minutes",
        security_preferences["session_timeout_minutes"],
    )
    state.setdefault(
        "security_settings_status",
        (
            "Optional security is enabled. Restart after changing startup policies."
            if security_preferences["security_enabled"]
            else "Optional security is disabled. Enable it below to activate these controls."
        ),
    )
    state.setdefault("security_settings_status_color", "info")
    state.setdefault(
        "security_cors_options",
        [
            {"text": "Same origin (recommended)", "value": "same_origin"},
            {"text": "One trusted origin", "value": "trusted_origin"},
            {"text": "Any origin (unsafe)", "value": "any"},
        ],
    )

    def publish_security_preferences(preferences: dict[str, Any]) -> None:
        state.security_enabled = preferences["security_enabled"]
        state.security_allow_network = preferences["bind_mode"] == "network"
        state.security_cors_mode = preferences["cors_mode"]
        state.security_cors_origin = preferences["cors_origin"]
        state.security_headers_enabled = preferences["security_headers"]
        state.security_api_key_enabled = preferences["api_key_enabled"]
        state.security_api_key_configured = bool(preferences["api_key_hash"])
        state.security_api_key_new = ""
        state.security_max_request_mb = preferences["max_request_mb"]
        state.security_websocket_max_message_mb = preferences[
            "websocket_max_message_mb"
        ]
        state.security_session_timeout_enabled = preferences["session_timeout_enabled"]
        state.security_session_timeout_minutes = preferences["session_timeout_minutes"]

    @state.change("active_tab")
    def refresh_backup_preview(active_tab, **_):
        if int(active_tab) == 6:
            state.app_state_backup_json = export_app_state_json()
            state.dirty("app_state_backup_json")
            state.flush()

    @state.change("app_state_restore_upload")
    def prepare_restore(app_state_restore_upload, **_):
        if not app_state_restore_upload:
            return
        try:
            name, content = _uploaded_bytes(app_state_restore_upload)
            if not name.lower().endswith(".json"):
                raise ValueError("Choose a .json app-state backup.")
            if len(content) > MAX_APP_STATE_UPLOAD_BYTES:
                raise ValueError("The app-state backup exceeds the 2 MB limit.")

            text = content.decode("utf-8-sig")
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("The backup must contain a JSON object.")
            if "case_config" not in parsed or "run_history" not in parsed:
                raise ValueError("This file is not a FOAMTrame app-state backup.")

            state.app_state_restore_pending = text
            state.app_state_restore_name = name
            state.app_state_settings_status = f"{name} is valid and ready to restore."
            state.app_state_settings_status_color = "info"
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            state.app_state_restore_pending = ""
            state.app_state_restore_name = ""
            state.app_state_settings_status = f"Invalid JSON backup: {exc}"
            state.app_state_settings_status_color = "error"
        except Exception as exc:
            state.app_state_restore_pending = ""
            state.app_state_restore_name = ""
            state.app_state_settings_status = str(exc)
            state.app_state_settings_status_color = "error"
        state.flush()

    def restore_app_state():
        if not state.app_state_restore_pending:
            return
        try:
            restored = restore_app_state_json(state.app_state_restore_pending)
            config = restored["case_config"]
            state.case_root = config["CASE_ROOT"]
            state.docker_image = config["DOCKER_IMAGE"]
            state.openfoam_version = config["OPENFOAM_VERSION"]
            state.active_case = config["ACTIVE_CASE"]
            state.run_history = restored["run_history"]
            publish_security_preferences(restored["security_preferences"])
            state.app_state_backup_json = json.dumps(restored, indent=2) + "\n"
            state.app_state_restore_pending = ""
            state.app_state_restore_name = ""
            state.app_state_restore_upload = None
            state.app_state_settings_status = "App state restored successfully."
            state.app_state_settings_status_color = "success"
            state.flush()
            if hasattr(ctrl, "scan_cases"):
                ctrl.scan_cases()
        except Exception as exc:
            state.app_state_settings_status = f"Restore failed: {exc}"
            state.app_state_settings_status_color = "error"
            state.flush()

    ctrl.restore_app_state = restore_app_state

    def generate_api_key():
        state.security_api_key_new = secrets.token_urlsafe(32)
        state.security_settings_status = "A new API key was generated. Copy it before saving; it is stored only as a hash."
        state.security_settings_status_color = "warning"
        state.flush()

    ctrl.generate_security_api_key = generate_api_key

    def save_security_settings():
        try:
            current = load_security_preferences()
            api_key_hash = current.get("api_key_hash", "")
            new_api_key = str(state.security_api_key_new or "").strip()
            if state.security_api_key_enabled and new_api_key:
                api_key_hash = hash_api_key(new_api_key)
            elif not state.security_api_key_enabled:
                api_key_hash = ""

            preferences = normalise_security_preferences(
                {
                    "security_enabled": state.security_enabled,
                    "bind_mode": (
                        "network" if state.security_allow_network else "loopback"
                    ),
                    "cors_mode": state.security_cors_mode,
                    "cors_origin": state.security_cors_origin,
                    "security_headers": state.security_headers_enabled,
                    "api_key_enabled": state.security_api_key_enabled,
                    "api_key_hash": api_key_hash,
                    "max_request_mb": state.security_max_request_mb,
                    "websocket_max_message_mb": (
                        state.security_websocket_max_message_mb
                    ),
                    "session_timeout_enabled": (state.security_session_timeout_enabled),
                    "session_timeout_minutes": (state.security_session_timeout_minutes),
                }
            )
            if not update_security_preferences(preferences):
                raise OSError("Security preferences could not be saved.")
            publish_security_preferences(preferences)
            if preferences["security_enabled"]:
                state.security_settings_status = (
                    "Optional security enabled. Restart FOAMTrame to apply server "
                    "binding, CORS headers, WebSocket limits, and session timeout."
                )
            else:
                state.security_settings_status = (
                    "Optional security disabled. Restart FOAMTrame to remove any "
                    "startup-time security policies."
                )
            state.security_settings_status_color = "success"
        except Exception as exc:
            state.security_settings_status = f"Security settings were not saved: {exc}"
            state.security_settings_status_color = "error"
        state.flush()

    ctrl.save_security_settings = save_security_settings


def build_settings_drawer():
    with html.Div(v_show="active_tab === 6", classes="pa-4"):
        with html.Div(classes="d-flex align-center mb-3"):
            vuetify.VIcon("mdi-cog-outline", color="cyan darken-3", classes="mr-2")
            html.Div("Settings", classes="text-subtitle-1 font-weight-bold")
        html.P(
            "Manage portable app state and optional server security policies.",
            classes="text-caption mb-3",
            style="color: #475569; line-height: 1.5;",
        )
        vuetify.VAlert(
            "{{ app_state_settings_status }}",
            type=("app_state_settings_status_color", "info"),
            dense=True,
            outlined=True,
        )


def build_settings_content():
    from trame.app import get_server

    server = get_server()
    assert server is not None
    state, ctrl = server.state, server.controller

    download_exec = client.JSEval(
        exec="utils.download($event.name, $event.content, $event.mime_type)"
    )

    def backup_app_state():
        try:
            backup_json = export_app_state_json()
            state.app_state_backup_json = backup_json
            state.dirty("app_state_backup_json")
            state.flush()
            download_exec.exec(
                {
                    "name": "foamtrame-app-state.json",
                    "content": backup_json,
                    "mime_type": "application/json;charset=utf-8",
                }
            )
            state.app_state_settings_status = (
                "Backup download started. Check your browser downloads."
            )
            state.app_state_settings_status_color = "success"
        except Exception as exc:
            state.app_state_settings_status = f"Backup failed: {exc}"
            state.app_state_settings_status_color = "error"
        state.flush()

    ctrl.backup_app_state = backup_app_state

    with vuetify.VContainer(
        fluid=True,
        classes="fill-height pa-6 settings-page",
        v_if="active_tab === 6",
    ):
        with vuetify.VRow(justify="center", classes="settings-page-row"):
            with vuetify.VCol(cols="12", md="10", lg="8", xl="7"):
                with vuetify.VCard(classes="glass-card settings-glass-card pa-6"):
                    with html.Div(classes="d-flex align-center mb-2"):
                        vuetify.VIcon(
                            "mdi-database-cog-outline",
                            classes="settings-title-icon mr-3",
                        )
                        html.H2("App State", classes="settings-title")
                    html.P(
                        "Back up and restore your case configuration and Run/Log history as one versioned JSON file.",
                        classes="settings-description mb-6",
                    )

                    with vuetify.VCard(classes="settings-action-card pa-5 mb-5"):
                        with html.Div(classes="settings-action-layout"):
                            with html.Div(classes="settings-action-copy"):
                                html.H3(
                                    "Backup App State", classes="settings-action-title"
                                )
                                html.P(
                                    "Download the current configuration and up to 100 recent run-history entries.",
                                    classes="settings-action-description",
                                )
                            with vuetify.VBtn(
                                click=ctrl.backup_app_state,
                                classes="theme-btn-primary settings-action-button",
                            ):
                                vuetify.VIcon("mdi-download-outline", classes="mr-2")
                                html.Span("Backup JSON")

                    with vuetify.VCard(classes="settings-action-card pa-5"):
                        html.H3("Restore App State", classes="settings-action-title")
                        html.P(
                            "Choose a FOAMTrame JSON backup. The file is validated before Restore is enabled.",
                            classes="settings-action-description mb-4",
                        )
                        vuetify.VFileInput(
                            v_model=("app_state_restore_upload",),
                            label="Choose app-state backup",
                            accept="application/json,.json",
                            prepend_icon="mdi-file-code-outline",
                            outlined=True,
                            show_size=True,
                            classes="settings-file-input",
                        )
                        vuetify.VAlert(
                            "{{ app_state_settings_status }}",
                            type=("app_state_settings_status_color", "info"),
                            dense=True,
                            text=True,
                            classes="mb-4",
                        )
                        with vuetify.VBtn(
                            click=ctrl.restore_app_state,
                            block=True,
                            classes="theme-btn-warning settings-restore-button",
                            disabled=("!app_state_restore_pending",),
                        ):
                            vuetify.VIcon("mdi-restore", classes="mr-2")
                            html.Span("Restore App State")

                with vuetify.VCard(
                    classes="glass-card settings-glass-card settings-security-card pa-6 mt-5"
                ):
                    with html.Div(classes="d-flex align-center mb-2"):
                        vuetify.VIcon(
                            "mdi-shield-lock-outline",
                            classes="settings-title-icon mr-3",
                        )
                        html.H2("Security", classes="settings-title")
                    html.P(
                        "Optional controls for network exposure, browser origins, API access, and resource limits.",
                        classes="settings-description mb-5",
                    )

                    vuetify.VAlert(
                        "{{ security_settings_status }}",
                        type=("security_settings_status_color", "info"),
                        dense=True,
                        text=True,
                        classes="mb-5 security-settings-alert",
                    )

                    with vuetify.VCard(classes="settings-action-card pa-5 mb-4"):
                        html.H3("Optional Security", classes="settings-action-title")
                        html.P(
                            "Disabled by default. Enable this master switch before any policy below is enforced.",
                            classes="settings-action-description mb-3",
                        )
                        vuetify.VSwitch(
                            v_model=("security_enabled", False),
                            label="Enable optional security controls",
                            color="cyan darken-2",
                            inset=True,
                            hide_details=True,
                            classes="security-setting-switch",
                        )

                    with vuetify.VCard(
                        classes="settings-action-card pa-5 mb-4",
                        disabled=("!security_enabled",),
                    ):
                        html.H3(
                            "Network & Browser Access", classes="settings-action-title"
                        )
                        html.P(
                            "Loopback-only access is safest. Network access and CORS changes require a restart.",
                            classes="settings-action-description mb-3",
                        )
                        vuetify.VSwitch(
                            v_model=("security_allow_network", False),
                            label="Allow access from other devices (bind to 0.0.0.0)",
                            color="warning",
                            inset=True,
                            hide_details=True,
                            classes="security-setting-switch mb-4",
                        )
                        vuetify.VSelect(
                            v_model=("security_cors_mode", "same_origin"),
                            items=("security_cors_options",),
                            label="CORS policy",
                            outlined=True,
                            dense=True,
                            hide_details=True,
                            classes="mb-4",
                        )
                        vuetify.VTextField(
                            v_model=("security_cors_origin", ""),
                            label="Trusted origin",
                            placeholder="https://example.com",
                            outlined=True,
                            dense=True,
                            hide_details=True,
                            v_if="security_cors_mode === 'trusted_origin'",
                            classes="mb-4",
                        )
                        vuetify.VAlert(
                            "Any-origin CORS allows every website to read eligible responses. Use it only for an intentionally public deployment.",
                            type="warning",
                            dense=True,
                            text=True,
                            v_if="security_cors_mode === 'any'",
                            classes="mb-4",
                        )
                        vuetify.VSwitch(
                            v_model=("security_headers_enabled", True),
                            label="Send restrictive browser security headers",
                            color="cyan darken-2",
                            inset=True,
                            hide_details=True,
                            classes="security-setting-switch",
                        )

                    with vuetify.VCard(
                        classes="settings-action-card pa-5 mb-4",
                        disabled=("!security_enabled",),
                    ):
                        html.H3("Resource Limits", classes="settings-action-title")
                        html.P(
                            "Bound request and WebSocket message sizes to reduce accidental or hostile memory pressure.",
                            classes="settings-action-description mb-4",
                        )
                        with vuetify.VRow():
                            with vuetify.VCol(cols="12", sm="6"):
                                vuetify.VTextField(
                                    v_model=("security_max_request_mb", 2),
                                    label="Maximum API request (MB)",
                                    type="number",
                                    min="1",
                                    max="64",
                                    outlined=True,
                                    dense=True,
                                    hide_details=True,
                                )
                            with vuetify.VCol(cols="12", sm="6"):
                                vuetify.VTextField(
                                    v_model=("security_websocket_max_message_mb", 4),
                                    label="Maximum WebSocket message (MB)",
                                    type="number",
                                    min="1",
                                    max="64",
                                    outlined=True,
                                    dense=True,
                                    hide_details=True,
                                )

                    with vuetify.VCard(
                        classes="settings-action-card pa-5 mb-4",
                        disabled=("!security_enabled",),
                    ):
                        html.H3("Session Timeout", classes="settings-action-title")
                        html.P(
                            "After the last browser disconnects, stop FOAMTrame once the grace period expires. Active browser sessions are never interrupted.",
                            classes="settings-action-description mb-3",
                        )
                        vuetify.VSwitch(
                            v_model=("security_session_timeout_enabled", False),
                            label="Enable no-client session timeout",
                            color="cyan darken-2",
                            inset=True,
                            hide_details=True,
                            classes="security-setting-switch mb-4",
                        )
                        vuetify.VTextField(
                            v_model=("security_session_timeout_minutes", 30),
                            label="Grace period (minutes)",
                            type="number",
                            min="1",
                            max="1440",
                            outlined=True,
                            dense=True,
                            hide_details=True,
                            disabled=("!security_session_timeout_enabled",),
                        )

                    with vuetify.VCard(
                        classes="settings-action-card pa-5 mb-5",
                        disabled=("!security_enabled",),
                    ):
                        html.H3("Companion API Key", classes="settings-action-title")
                        html.P(
                            "Require X-FOAMTrame-API-Key for POST requests to the optional Flask API. The key is stored as a PBKDF2 hash.",
                            classes="settings-action-description mb-3",
                        )
                        vuetify.VSwitch(
                            v_model=("security_api_key_enabled", False),
                            label="Protect mutating companion API requests",
                            color="cyan darken-2",
                            inset=True,
                            hide_details=True,
                            classes="security-setting-switch mb-4",
                        )
                        with html.Div(
                            v_if="security_api_key_enabled",
                            classes="security-api-key-layout",
                        ):
                            vuetify.VTextField(
                                v_model=("security_api_key_new", ""),
                                label=(
                                    "security_api_key_configured ? 'New API key (leave blank to keep current)' : 'New API key'",
                                ),
                                type="password",
                                outlined=True,
                                dense=True,
                                hide_details=True,
                                autocomplete="new-password",
                            )
                            with vuetify.VBtn(
                                click=ctrl.generate_security_api_key,
                                outlined=True,
                                color="cyan darken-3",
                                classes="security-generate-key-button",
                            ):
                                vuetify.VIcon("mdi-key-plus", classes="mr-2")
                                html.Span("Generate")
                        html.P(
                            "Configured key present. Enter a new value only to rotate it.",
                            v_if="security_api_key_enabled && security_api_key_configured",
                            classes="settings-action-description mt-3 mb-0",
                        )

                    with vuetify.VBtn(
                        click=ctrl.save_security_settings,
                        block=True,
                        classes="theme-btn-primary settings-security-save-button",
                    ):
                        vuetify.VIcon("mdi-content-save-lock-outline", classes="mr-2")
                        html.Span("Save Security Settings")
