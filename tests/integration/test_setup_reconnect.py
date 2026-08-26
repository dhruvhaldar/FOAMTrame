from __future__ import annotations

import asyncio

from tabs import setup_tab


class FakeState:
    def __init__(self):
        self._values = {}

    def setdefault(self, key, value):
        return self._values.setdefault(key, value)

    def __getattr__(self, key):
        try:
            return self._values[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        if key == "_values":
            super().__setattr__(key, value)
        else:
            self._values[key] = value

    def change(self, *_keys):
        return lambda callback: callback

    def dirty(self, *_keys):
        pass

    def flush(self):
        pass


class FakeController:
    def __init__(self):
        self.events = {}

    def add(self, name):
        def register(callback):
            self.events.setdefault(name, []).append(callback)
            return callback

        return register


class FakeServer:
    def __init__(self):
        self.state = FakeState()
        self.controller = FakeController()
        self.pushes = []

    def force_state_push(self, *keys):
        self.pushes.append(keys)


class DeferredThread:
    instances = []

    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon
        self.instances.append(self)

    def start(self):
        pass


class FakeContainers:
    def run(self, *_args, **_kwargs):
        return b""


class FakeDockerClient:
    def __init__(self):
        self.containers = FakeContainers()


def test_docker_worker_publishes_completion_and_reconnect_snapshot(
    monkeypatch, tmp_path
):
    DeferredThread.instances = []
    monkeypatch.setattr(setup_tab.threading, "Thread", DeferredThread)
    monkeypatch.setattr(setup_tab.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        setup_tab,
        "load_config",
        lambda: {
            "CASE_ROOT": str(tmp_path),
            "DOCKER_IMAGE": "registry/example_openfoam:v12",
            "OPENFOAM_VERSION": "12",
            "ACTIVE_CASE": "",
        },
    )
    monkeypatch.setattr(setup_tab, "save_config", lambda _updates: None)

    server = FakeServer()
    setup_tab.setup_setup_tab(server)

    async def exercise_callbacks():
        server.controller.events["on_server_ready"][0]()
        DeferredThread.instances[0].target()
        await asyncio.sleep(0)
        server.controller.events["on_client_connected"][0]()

    asyncio.run(exercise_callbacks())

    assert server.state.docker_checking is False
    assert server.state.setup_status == "Docker executable not found in PATH."
    assert any("docker_checking" in keys for keys in server.pushes)
    assert any(
        "setup_status" in keys and "openfoam_runtime_label" in keys
        for keys in server.pushes
    )


def test_tutorial_import_publishes_completion_to_connected_client(
    monkeypatch, tmp_path
):
    DeferredThread.instances = []
    monkeypatch.setattr(setup_tab.threading, "Thread", DeferredThread)
    monkeypatch.setattr(setup_tab, "get_docker_client", lambda: FakeDockerClient())
    monkeypatch.setattr(
        setup_tab,
        "load_config",
        lambda: {
            "CASE_ROOT": str(tmp_path),
            "DOCKER_IMAGE": "registry/example_openfoam:v12",
            "OPENFOAM_VERSION": "12",
            "ACTIVE_CASE": "",
        },
    )
    saved_updates = []
    monkeypatch.setattr(setup_tab, "save_config", saved_updates.append)

    server = FakeServer()
    setup_tab.setup_setup_tab(server)
    server.state.selected_tutorial = "fluid/aerofoilNACA0012Steady"
    (tmp_path / "aerofoilNACA0012Steady").mkdir()

    async def exercise_import():
        server.controller.events["on_server_ready"][0]()
        server.controller.import_tutorial_case()
        DeferredThread.instances[-1].target()
        await asyncio.sleep(0)

    asyncio.run(exercise_import())

    assert server.state.setup_status == (
        "Tutorial aerofoilNACA0012Steady imported successfully."
    )
    assert server.state.active_case == "aerofoilNACA0012Steady"
    assert server.state.cases_list == ["aerofoilNACA0012Steady"]
    assert {"ACTIVE_CASE": "aerofoilNACA0012Steady"} in saved_updates
    assert any(
        "setup_status" in keys
        and "setup_status_color" in keys
        and "cases_list" in keys
        and "active_case" in keys
        for keys in server.pushes
    )
