import json

import pytest

from android_collector.client import AndroidAppiumClient
from collector_core.webdriver import parse_ui_tree
from ios_collector.client import IOSAppiumClient


def test_android_client_has_android_only_session_and_package_boundary(monkeypatch):
    calls = []
    client = AndroidAppiumClient("http://127.0.0.1:4723")

    def fake_call(method, path, payload=None, **kwargs):
        calls.append((method, path, payload))
        if path == "/session":
            return {"sessionId": "android-session"}
        if path.endswith("/appium/device/current_package"):
            return "com.example.android"
        return None

    monkeypatch.setattr(client, "_call", fake_call)

    assert client.start_session({"automationName": "UiAutomator2"}) == "android-session"
    assert calls[0][2]["capabilities"]["alwaysMatch"]["platformName"] == "Android"
    assert client.get_current_app_id() == "com.example.android"
    client.open_deep_link("https://example.test/item/1", "com.example.android")
    assert calls[-1][2]["args"] == [{
        "url": "https://example.test/item/1",
        "package": "com.example.android",
    }]


def test_ios_client_has_ios_only_session_and_bundle_boundary(monkeypatch):
    calls = []
    client = IOSAppiumClient("http://127.0.0.1:4723")

    def fake_call(method, path, payload=None, **kwargs):
        calls.append((method, path, payload))
        if path == "/session":
            return {"sessionId": "ios-session"}
        if payload and payload.get("script") == "mobile: activeAppInfo":
            return {"bundleId": "com.example.ios", "name": "Example"}
        return None

    monkeypatch.setattr(client, "_call", fake_call)

    assert client.start_session({"automationName": "XCUITest"}) == "ios-session"
    assert calls[0][2]["capabilities"]["alwaysMatch"]["platformName"] == "iOS"
    assert client.get_current_app_id() == "com.example.ios"
    client.open_deep_link("example://item/1", "com.example.ios")
    assert calls[-1][2]["args"] == [{
        "url": "example://item/1",
        "bundleId": "com.example.ios",
    }]


def test_shared_tree_parser_understands_android_and_ios_nodes():
    android = parse_ui_tree(
        '<hierarchy><node class="android.widget.Button" text="打开" '
        'resource-id="open" clickable="true" bounds="[10,20][110,64]" /></hierarchy>'
    )
    ios = parse_ui_tree(
        '<AppiumAUT><XCUIElementTypeButton type="XCUIElementTypeButton" name="open" '
        'label="Open" enabled="true" visible="true" x="10" y="20" width="100" height="44" />'
        '</AppiumAUT>'
    )

    assert android[0].role == "button"
    assert android[0].text == "打开"
    assert ios[0].role == "button"
    assert ios[0].text == "Open"
    assert ios[0].bounds.width == 100


def test_base_client_retries_get_but_never_retries_post(monkeypatch):
    get_client = AndroidAppiumClient(
        "http://127.0.0.1:4723", read_retries=2, retry_delay=0
    )
    get_client.session_id = "session"
    get_calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"value":"com.example"}'

    def transient_get(request, timeout):
        get_calls.append(request.method)
        if len(get_calls) < 3:
            raise TimeoutError("temporary")
        return FakeResponse()

    monkeypatch.setattr("collector_core.webdriver.request.urlopen", transient_get)
    assert get_client.get_current_app_id() == "com.example"
    assert get_calls == ["GET", "GET", "GET"]

    post_client = IOSAppiumClient(
        "http://127.0.0.1:4723", read_retries=2, retry_delay=0
    )
    post_client.session_id = "session"
    post_calls = []

    def failing_post(request, timeout):
        post_calls.append(request.method)
        raise TimeoutError("uncertain write")

    monkeypatch.setattr("collector_core.webdriver.request.urlopen", failing_post)
    with pytest.raises(TimeoutError, match="uncertain write"):
        post_client.open_deep_link("example://item", "com.example")
    assert post_calls == ["POST"]
