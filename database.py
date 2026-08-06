from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger("FOAMTrame")

DATABASE_PATH = Path("foamtrame.db")
SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_seconds(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).removesuffix("s"))
    except (TypeError, ValueError):
        return None


class AppDatabase:
    """Small repository around FOAMTrame's embedded SQLite database.

    Connections are intentionally short-lived so background simulation threads do
    not share sqlite3 connection objects. The public methods form the persistence
    boundary that can later be backed by PostgreSQL without changing UI code.
    """

    def __init__(self, path: str | Path = DATABASE_PATH):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._lock, self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_config (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS simulation_runs (
                    run_key TEXT PRIMARY KEY,
                    position INTEGER NOT NULL,
                    case_name TEXT NOT NULL DEFAULT '',
                    command TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    started_at TEXT,
                    ended_at TEXT,
                    duration_seconds REAL,
                    record_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_simulation_runs_position
                    ON simulation_runs(position);
                CREATE INDEX IF NOT EXISTS ix_simulation_runs_case_status
                    ON simulation_runs(case_name, status);

                CREATE TABLE IF NOT EXISTS cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    root_path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'workspace',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(root_path, name)
                );

                -- Durable audit/command records for the planned chatbot. The UI
                -- and chatbot should both invoke application services which write
                -- here; the chatbot should never automate DOM clicks.
                CREATE TABLE IF NOT EXISTS automation_actions (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT,
                    parent_action_id TEXT,
                    action_type TEXT NOT NULL,
                    target TEXT,
                    parameters_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    requires_confirmation INTEGER NOT NULL DEFAULT 0,
                    approved_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    result_json TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(parent_action_id) REFERENCES automation_actions(id)
                );

                CREATE INDEX IF NOT EXISTS ix_automation_actions_status_created
                    ON automation_actions(status, created_at);
                """
            )
            connection.execute(
                """
                INSERT INTO schema_metadata(key, value) VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )
            connection.commit()

    def has_app_state(self) -> bool:
        self.initialize()
        with self.connection() as connection:
            row = connection.execute(
                "SELECT value FROM schema_metadata WHERE key = 'state_initialized'"
            ).fetchone()
            return row is not None and row["value"] == "1"

    def load_app_state(self) -> dict[str, Any]:
        self.initialize()
        with self.connection() as connection:
            config_rows = connection.execute(
                "SELECT key, value_json FROM app_config ORDER BY key"
            ).fetchall()
            run_rows = connection.execute(
                "SELECT record_json FROM simulation_runs ORDER BY position LIMIT 100"
            ).fetchall()

        config = {row["key"]: json.loads(row["value_json"]) for row in config_rows}
        history = [json.loads(row["record_json"]) for row in run_rows]
        return {"version": SCHEMA_VERSION, "case_config": config, "run_history": history}

    def save_app_state(self, data: dict[str, Any]) -> None:
        self.initialize()
        config = data["case_config"]
        history = data["run_history"][:100]
        now = _utc_now()

        with self._lock, self.connection() as connection, connection:
            connection.execute("DELETE FROM app_config")
            connection.executemany(
                "INSERT INTO app_config(key, value_json, updated_at) VALUES(?, ?, ?)",
                [
                    (key, json.dumps(value, ensure_ascii=False), now)
                    for key, value in config.items()
                ],
            )

            connection.execute("DELETE FROM simulation_runs")
            run_records = []
            used_keys: set[str] = set()
            for position, record in enumerate(history):
                base_key = str(record.get("id") or f"legacy-{position}")
                run_key = base_key
                suffix = 1
                while run_key in used_keys:
                    suffix += 1
                    run_key = f"{base_key}-{suffix}"
                used_keys.add(run_key)
                run_records.append(
                    (
                        run_key,
                        position,
                        str(record.get("case_name") or ""),
                        str(record.get("command") or ""),
                        str(record.get("status") or ""),
                        record.get("start_time"),
                        record.get("end_time"),
                        _duration_seconds(record.get("duration")),
                        json.dumps(record, ensure_ascii=False),
                    )
                )
            connection.executemany(
                """
                INSERT INTO simulation_runs(
                    run_key, position, case_name, command, status, started_at,
                    ended_at, duration_seconds, record_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                run_records,
            )
            connection.execute(
                """
                INSERT INTO schema_metadata(key, value) VALUES('state_initialized', '1')
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """
            )


database = AppDatabase()

