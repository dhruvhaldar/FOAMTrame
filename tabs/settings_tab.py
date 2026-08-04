from __future__ import annotations

import base64
import json
from typing import Any

from trame.widgets import client, html, vuetify

from app_state import export_app_state_json, restore_app_state_json

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
            return name, base64.b64decode(encoded, validate=True)
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


def build_settings_drawer():
    from trame.app import get_server

    server = get_server()
    state = server.state

    with html.Div(v_show="active_tab === 6", classes="pa-4"):
        with html.Div(classes="d-flex align-center mb-3"):
            vuetify.VIcon("mdi-cog-outline", color="cyan darken-3", classes="mr-2")
            html.Div("Settings", classes="text-subtitle-1 font-weight-bold")
        html.P(
            "Back up or restore configuration and run history from one portable JSON file.",
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
    state, ctrl = server.state, server.controller

    download_exec = client.JSEval(
        exec=(
            "utils.download($event.name, $event.content, $event.mime_type)",
        )
    )

    def backup_app_state():
        backup_json = export_app_state_json()
        state.app_state_backup_json = backup_json
        state.app_state_settings_status = "App-state backup downloaded."
        state.app_state_settings_status_color = "success"
        state.dirty("app_state_backup_json")
        state.flush()
        download_exec.exec(
            {
                "name": "foamtrame-app-state.json",
                "content": backup_json,
                "mime_type": "application/json",
            }
        )

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
                        vuetify.VIcon("mdi-database-cog-outline", classes="settings-title-icon mr-3")
                        html.H2("App State", classes="settings-title")
                    html.P(
                        "Back up and restore your case configuration and Run/Log history as one versioned JSON file.",
                        classes="settings-description mb-6",
                    )

                    with vuetify.VCard(classes="settings-action-card pa-5 mb-5"):
                        with html.Div(classes="settings-action-layout"):
                            with html.Div(classes="settings-action-copy"):
                                html.H3("Backup App State", classes="settings-action-title")
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
