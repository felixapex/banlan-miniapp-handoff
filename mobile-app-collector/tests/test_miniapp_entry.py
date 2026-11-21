from pathlib import Path

import pytest

from miniapp_collector.client import (
    MiniappAdbClient,
    classify_miniapp_link,
)
from miniapp_collector import cli as miniapp_cli


@pytest.mark.parametrize("value, expected", [
    ("#小程序://示例品牌/Abc_123", "wechat_share_text"),
    ("weixin://dl/business/?t=abc123", "wechat_scheme"),
    ("https://wxaurl.cn/abc123", "wechat_url_link"),
])
def test_miniapp_link_classifier_accepts_supported_wechat_links(value, expected):
    assert classify_miniapp_link(value) == expected


def test_miniapp_link_classifier_rejects_ordinary_web_urls():
    with pytest.raises(ValueError, match="unsupported miniapp link"):
        classify_miniapp_link("https://example.com/")


def test_miniapp_entry_has_its_own_link_and_safety_arguments():
    parser = miniapp_cli.build_parser()
    args = parser.parse_args([
        "capture",
        "--link", "weixin://dl/business/?t=abc123",
        "--dedicated-test-account",
        "--out", "out/miniapp",
    ])
    assert args.command == "capture"
    assert args.dedicated_test_account is True
    assert not hasattr(args, "platform")
    assert not hasattr(args, "appium_url")


def test_miniapp_capture_refuses_before_device_access_without_safety_ack(monkeypatch, tmp_path):
    accessed = []

    class ForbiddenClient:
        def __init__(self, *_args, **_kwargs):
            accessed.append(True)

    monkeypatch.setattr(miniapp_cli, "MiniappAdbClient", ForbiddenClient)
    with pytest.raises(SystemExit, match="dedicated test account"):
        miniapp_cli.main([
            "capture",
            "--link", "weixin://dl/business/?t=abc123",
            "--out", str(tmp_path),
        ])
    assert accessed == []


def test_miniapp_adb_client_converts_capture_to_shared_evidence(monkeypatch, tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (390).to_bytes(4, "big") + (844).to_bytes(4, "big")
    xml = (
        b'<hierarchy><node class="android.widget.Button" text="Open" '
        b'resource-id="open" clickable="true" enabled="true" '
        b'bounds="[10,20][110,64]" /></hierarchy>'
    )
    client = MiniappAdbClient("adb", target_id="miniapp:test", serial="emulator-5554")
    monkeypatch.setattr(client, "screenshot", lambda: png)
    monkeypatch.setattr(client, "hierarchy", lambda: xml)

    screen = client.capture_screen(tmp_path, "screen-0001")

    assert screen.width == 390
    assert screen.height == 844
    assert screen.elements[0].text == "Open"
    assert screen.elements[0].role == "button"
    assert Path(screen.screenshot_path).read_bytes() == png


def test_shared_explorer_can_label_non_appium_capture_source(tmp_path):
    from collector_core.evidence import Bounds, ElementEvidence, ScreenEvidence
    from collector_core.explorer import SafeStateExplorer

    class FakeMiniappClient:
        def get_current_app_id(self):
            return "miniapp:test"

        def capture_screen(self, out_dir, screen_id, state_id="default"):
            return ScreenEvidence(
                screen_id=screen_id,
                state_id=state_id,
                width=390,
                height=844,
                screenshot_path=str(Path(out_dir) / f"{screen_id}.png"),
                screenshot_sha256="sha",
                ui_tree_path=None,
                elements=[],
                interactions=[],
            )

        def tap_at(self, _x, _y):
            raise AssertionError("no controls")

        def back(self):
            raise AssertionError("no navigation")

        def swipe(self, *_args, **_kwargs):
            raise AssertionError("scroll disabled")

    app = SafeStateExplorer(
        FakeMiniappClient(), settle_seconds=0, sleep_fn=lambda _seconds: None
    ).explore(
        app_id="miniapp:test",
        app_name="Test Miniapp",
        platform="wechat-miniapp",
        app_version=None,
        capture_source="adb-wechat",
        out_dir=tmp_path,
        max_actions_per_screen=0,
        max_scrolls_per_screen=0,
    )
    assert app.capture_source == "adb-wechat"
