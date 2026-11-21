import json

import pytest

from collector_core import command
from collector_core.evidence import AppEvidence


class FakeClient:
    created = []

    def __init__(self, base_url):
        self.base_url = base_url
        self.started = None
        self.stopped = False
        self.deep_links = []
        self.__class__.created.append(self)

    def start_session(self, options):
        self.started = options
        return "session"

    def stop_session(self):
        self.stopped = True

    def open_deep_link(self, url, app_id):
        self.deep_links.append((url, app_id))


def test_capture_command_writes_checkpoint_evidence_and_coverage(monkeypatch, tmp_path):
    class FakeExplorer:
        def __init__(self, _client, **options):
            self.progress_callback = options["progress_callback"]
            assert options["progress_every"] == 4

        def explore(self, **kwargs):
            app = AppEvidence(
                app_id=kwargs["app_id"],
                app_name=kwargs["app_name"],
                platform=kwargs["platform"],
                app_version=kwargs["app_version"],
                capture_source="appium",
                screens=[],
                flows=[],
            )
            self.progress_callback(app)
            return app

    monkeypatch.setattr(command, "SafeStateExplorer", FakeExplorer)
    FakeClient.created = []
    parser = command.build_platform_parser(
        prog="android-collector",
        platform_label="Android",
    )
    args = parser.parse_args([
        "capture",
        "--appium-url", "http://127.0.0.1:4723",
        "--appium-options-json", '{"automationName":"UiAutomator2"}',
        "--app-id", "com.example",
        "--app-name", "Example",
        "--start-url", "https://example.test/item/1",
        "--start-url-settle-seconds", "0",
        "--progress-every", "4",
        "--out", str(tmp_path),
    ])

    assert command.run_command(
        args,
        platform="android",
        client_class=FakeClient,
    ) == 0

    assert (tmp_path / "checkpoint-evidence.json").is_file()
    assert (tmp_path / "evidence.json").is_file()
    coverage = json.loads((tmp_path / "interaction-coverage.json").read_text(encoding="utf-8"))
    assert coverage["status"] == "INCOMPLETE"
    client = FakeClient.created[0]
    assert client.started == {"automationName": "UiAutomator2"}
    assert client.deep_links == [("https://example.test/item/1", "com.example")]
    assert client.stopped is True


def test_capture_command_rejects_cross_platform_resume(monkeypatch, tmp_path):
    previous = AppEvidence(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version=None,
        capture_source="appium",
        screens=[],
        flows=[],
    )
    monkeypatch.setattr(command, "load_evidence", lambda _path: previous)
    parser = command.build_platform_parser(prog="ios-collector", platform_label="iOS")
    args = parser.parse_args([
        "capture",
        "--appium-url", "http://127.0.0.1:4723",
        "--appium-options-json", '{}',
        "--app-id", "com.example",
        "--app-name", "Example",
        "--resume-evidence", "android-evidence.json",
        "--out", str(tmp_path),
    ])

    with pytest.raises(SystemExit, match="platform mismatch"):
        command.run_command(args, platform="ios", client_class=FakeClient)
