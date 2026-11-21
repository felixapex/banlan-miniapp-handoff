import json

from android_collector import cli as android_cli
from ios_collector import cli as ios_cli


def test_android_entry_has_no_platform_switch():
    parser = android_cli.build_parser()
    capture = parser.parse_args([
        "capture",
        "--appium-url", "http://127.0.0.1:4723",
        "--appium-options-json", '{}',
        "--app-id", "com.example.android",
        "--app-name", "Example Android",
        "--out", "out/android",
    ])
    assert capture.command == "capture"
    assert not hasattr(capture, "platform")


def test_ios_entry_has_no_platform_switch():
    parser = ios_cli.build_parser()
    capture = parser.parse_args([
        "capture",
        "--appium-url", "http://127.0.0.1:4723",
        "--appium-options-json", '{}',
        "--app-id", "com.example.ios",
        "--app-name", "Example iOS",
        "--out", "out/ios",
    ])
    assert capture.command == "capture"
    assert not hasattr(capture, "platform")


def test_android_and_ios_entries_inject_their_own_client(monkeypatch, tmp_path):
    seen = []

    def fake_run(args, *, platform, client_class):
        seen.append((platform, client_class.__name__, args.app_id))
        return 0

    monkeypatch.setattr(android_cli, "run_command", fake_run)
    monkeypatch.setattr(ios_cli, "run_command", fake_run)

    common = [
        "capture",
        "--appium-url", "http://127.0.0.1:4723",
        "--appium-options-json", '{}',
        "--app-name", "Example",
        "--out", str(tmp_path),
    ]
    assert android_cli.main([*common, "--app-id", "com.example.android"]) == 0
    assert ios_cli.main([*common, "--app-id", "com.example.ios"]) == 0
    assert seen == [
        ("android", "AndroidAppiumClient", "com.example.android"),
        ("ios", "IOSAppiumClient", "com.example.ios"),
    ]
