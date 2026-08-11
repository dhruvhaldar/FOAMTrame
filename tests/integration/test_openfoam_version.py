from tabs.setup_tab import detect_openfoam_version


class FakeContainers:
    def __init__(self, output: bytes):
        self.output = output
        self.calls = []

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.output


class FakeDockerClient:
    def __init__(self, output: bytes):
        self.containers = FakeContainers(output)


def test_openfoam_version_is_read_from_container_environment():
    client = FakeDockerClient(b"12")

    version = detect_openfoam_version(client, "openfoam:test", "11")

    assert version == "12"
    args, kwargs = client.containers.calls[0]
    assert args[0] == "openfoam:test"
    assert args[1][-1] == "11"
    assert "WM_PROJECT_VERSION" in args[1][2]
    assert kwargs["remove"] is True
    assert kwargs["network_disabled"] is True
