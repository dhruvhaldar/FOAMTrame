from __future__ import annotations

import json
import tempfile
import threading
import unittest
from io import StringIO
from pathlib import Path

import app_state
from database import AppDatabase
from run import tee_stream

try:
    import pytest

    pytestmark = pytest.mark.integration
except ImportError:  # unittest remains dependency-free
    pass


def sample_state(case: str = "cavity") -> dict:
    return {
        "version": app_state.APP_STATE_VERSION,
        "case_config": {
            "CASE_ROOT": "C:/cases",
            "DOCKER_IMAGE": "openfoam:test",
            "OPENFOAM_VERSION": "12",
            "ACTIVE_CASE": case,
        },
        "plot_preferences": app_state.default_plot_preferences(),
        "security_preferences": app_state.default_security_preferences(),
        "run_history": [
            {
                "id": 42,
                "case_name": case,
                "command": "icoFoam",
                "status": "Completed",
                "start_time": "2026-08-06 10:00:00",
                "end_time": "2026-08-06 10:00:02",
                "duration": "2.0s",
            }
        ],
    }


class DatabaseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database = AppDatabase(self.root / "foamtrame.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schema_and_state_round_trip(self):
        state = sample_state()
        self.assertFalse(self.database.has_app_state())
        self.database.save_app_state(state)
        self.assertEqual(state, self.database.load_app_state())

        with self.database.connection() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

        self.assertTrue(
            {
                "app_config",
                "security_preferences",
                "simulation_runs",
                "cases",
                "automation_actions",
            }
            <= tables
        )
        self.assertEqual("wal", mode.lower())

    def test_failed_write_rolls_back_the_complete_state(self):
        original = sample_state()
        self.database.save_app_state(original)
        invalid = sample_state("invalid")
        invalid["run_history"][0]["not_json"] = {"a-set"}

        with self.assertRaises(TypeError):
            self.database.save_app_state(invalid)

        self.assertEqual(original, self.database.load_app_state())

    def test_concurrent_writers_leave_a_valid_snapshot(self):
        errors: list[Exception] = []

        def write(index: int):
            try:
                self.database.save_app_state(sample_state(f"case-{index}"))
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(errors)
        loaded = self.database.load_app_state()
        self.assertIn(
            loaded["case_config"]["ACTIVE_CASE"], {f"case-{i}" for i in range(8)}
        )
        self.assertEqual(1, len(loaded["run_history"]))


class AppStateMigrationIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.originals = (
            app_state.database,
            app_state.LEGACY_APP_STATE_FILE,
            app_state.LEGACY_CONFIG_FILE,
            app_state.LEGACY_RUN_HISTORY_FILE,
        )
        app_state.database = AppDatabase(self.root / "foamtrame.db")
        app_state.LEGACY_APP_STATE_FILE = self.root / "app_state.json"
        app_state.LEGACY_CONFIG_FILE = self.root / "case_config.json"
        app_state.LEGACY_RUN_HISTORY_FILE = self.root / "run_history.json"

    def tearDown(self):
        (
            app_state.database,
            app_state.LEGACY_APP_STATE_FILE,
            app_state.LEGACY_CONFIG_FILE,
            app_state.LEGACY_RUN_HISTORY_FILE,
        ) = self.originals
        self.temp_dir.cleanup()

    def test_legacy_migration_json_backup_and_restore(self):
        legacy = sample_state()
        app_state.LEGACY_APP_STATE_FILE.write_text(json.dumps(legacy), encoding="utf-8")

        self.assertEqual(legacy, app_state.load_app_state())
        backup = json.loads(app_state.export_app_state_json())
        self.assertEqual(legacy, backup)

        backup["case_config"]["ACTIVE_CASE"] = "motorBike"
        backup["plot_preferences"].update({"font": "roboto", "background": "black"})
        restored = app_state.restore_app_state_json(json.dumps(backup))
        self.assertEqual("motorBike", restored["case_config"]["ACTIVE_CASE"])
        self.assertEqual("motorBike", app_state.load_case_config()["ACTIVE_CASE"])
        self.assertEqual("roboto", app_state.load_plot_preferences()["font"])
        self.assertEqual("black", app_state.load_plot_preferences()["background"])
        self.assertEqual("loopback", app_state.load_security_preferences()["bind_mode"])
        self.assertTrue(app_state.LEGACY_APP_STATE_FILE.exists())


class LauncherLoggingIntegrationTest(unittest.TestCase):
    def test_child_output_is_copied_to_console_and_run_log(self):
        source = StringIO("first line\nsecond line\n")
        console = StringIO()
        run_log = StringIO()

        tee_stream(source, console, run_log)

        self.assertEqual(source.getvalue(), console.getvalue())
        self.assertEqual(source.getvalue(), run_log.getvalue())


if __name__ == "__main__":
    unittest.main()
