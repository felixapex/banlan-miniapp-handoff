from __future__ import annotations

from collector_core.webdriver import BaseAppiumClient


class IOSAppiumClient(BaseAppiumClient):
    """iOS-only Appium client backed by XCUITest and Bundle ID boundaries."""

    def start_session(self, appium_options: dict) -> str:
        return self._start_session("ios", appium_options)

    def get_current_app_id(self) -> str | None:
        value = self.execute_script("mobile: activeAppInfo", [])
        if not isinstance(value, dict):
            return None
        bundle_id = value.get("bundleId") or value.get("bundleID")
        return str(bundle_id) if bundle_id else None

    def open_deep_link(self, url: str, app_id: str) -> None:
        if not url:
            raise ValueError("deep link URL must not be empty")
        if not app_id:
            raise ValueError("iOS Bundle ID must not be empty")
        self.execute_script(
            "mobile: deepLink",
            [{"url": url, "bundleId": app_id}],
        )
