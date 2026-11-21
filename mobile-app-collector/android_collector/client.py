from __future__ import annotations

from collector_core.webdriver import BaseAppiumClient


class AndroidAppiumClient(BaseAppiumClient):
    """Android-only Appium client backed by UiAutomator2 and package boundaries."""

    def start_session(self, appium_options: dict) -> str:
        return self._start_session("android", appium_options)

    def get_current_app_id(self) -> str | None:
        value = self._call(
            "GET",
            self._session_path("/appium/device/current_package"),
        )
        return str(value) if value else None

    def open_deep_link(self, url: str, app_id: str) -> None:
        if not url:
            raise ValueError("deep link URL must not be empty")
        if not app_id:
            raise ValueError("Android package name must not be empty")
        self.execute_script(
            "mobile: deepLink",
            [{"url": url, "package": app_id}],
        )
