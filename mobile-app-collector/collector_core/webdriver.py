from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from urllib import request, error
import xml.etree.ElementTree as ET

from .evidence import Bounds, ElementEvidence, ScreenEvidence, sha256_file

_ANDROID_BOUNDS = re.compile(r"\[(?P<x1>-?\d+),(?P<y1>-?\d+)\]\[(?P<x2>-?\d+),(?P<y2>-?\d+)\]")


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() == "true"


def _role_from_node(attrs: dict[str, str]) -> str:
    raw = attrs.get("class") or attrs.get("type") or attrs.get("role") or "view"
    name = raw.split(".")[-1].removeprefix("XCUIElementType").lower()
    aliases = {
        "button": "button",
        "textview": "text",
        "statictext": "text",
        "textfield": "input",
        "edittext": "input",
        "image": "image",
        "imageview": "image",
        "switch": "switch",
        "cell": "listitem",
    }
    role = aliases.get(name, name or "view")
    if role in {"view", "text", "image"} and _bool(attrs.get("clickable")):
        return "button"
    return role


def _bounds_from_node(attrs: dict[str, str]) -> Bounds:
    raw = attrs.get("bounds")
    if raw:
        match = _ANDROID_BOUNDS.fullmatch(raw)
        if match:
            x1, y1, x2, y2 = (int(match.group(key)) for key in ("x1", "y1", "x2", "y2"))
            return Bounds(x=x1, y=y1, width=max(0, x2 - x1), height=max(0, y2 - y1))
    return Bounds(
        x=int(float(attrs.get("x", 0))),
        y=int(float(attrs.get("y", 0))),
        width=int(float(attrs.get("width", 0))),
        height=int(float(attrs.get("height", 0))),
    )


def parse_ui_tree(xml_text: str) -> list[ElementEvidence]:
    root = ET.fromstring(xml_text)
    elements: list[ElementEvidence] = []

    def walk(node: ET.Element, path: tuple[int, ...], parent_id: str | None) -> None:
        attrs = {str(k): str(v) for k, v in node.attrib.items()}
        bounds = _bounds_from_node(attrs)
        current_parent = parent_id
        if node is not root and (bounds.width > 0 or bounds.height > 0):
            content_description = attrs.get("content-desc")
            text = attrs.get("text") or attrs.get("label") or attrs.get("name") or content_description
            accessibility_id = (
                attrs.get("resource-id")
                or attrs.get("name")
                or attrs.get("accessibility-id")
                or content_description
            )
            path_suffix = "-".join(str(part) for part in path)
            base_id = accessibility_id or "element"
            evidence_id = f"{base_id}__{path_suffix}"
            element = ElementEvidence(
                evidence_id=evidence_id,
                role=_role_from_node(attrs),
                text=text,
                bounds=bounds,
                enabled=_bool(attrs.get("enabled"), True),
                selected=_bool(attrs.get("selected"), False),
                visible=_bool(attrs.get("visible"), True),
                accessibility_id=accessibility_id,
                parent_id=parent_id,
            )
            elements.append(element)
            current_parent = evidence_id

        for child_index, child in enumerate(list(node)):
            walk(child, path + (child_index,), current_parent)

    walk(root, (), None)
    return elements



class BaseAppiumClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        session_timeout: float = 120.0,
        read_retries: int = 2,
        retry_delay: float = 0.25,
    ):
        if read_retries < 0:
            raise ValueError("read_retries must be >= 0")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session_timeout = session_timeout
        self.read_retries = read_retries
        self.retry_delay = max(0.0, retry_delay)
        self.session_id: str | None = None
        self.platform: str | None = None

    def _call(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        timeout: float | None = None,
    ):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        attempts = self.read_retries + 1 if method.upper() == "GET" else 1
        for attempt in range(attempts):
            try:
                with request.urlopen(req, timeout=self.timeout if timeout is None else timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                break
            except error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"WebDriver {method} {path} failed: HTTP {exc.code}: {details}") from exc
            except TimeoutError:
                if attempt + 1 >= attempts:
                    raise
                if self.retry_delay:
                    time.sleep(self.retry_delay)
        return body.get("value")

    def _start_session(self, platform: str, appium_options: dict) -> str:
        platform = platform.lower()
        if platform not in {"android", "ios"}:
            raise ValueError("platform must be 'android' or 'ios'")
        payload = {
            "capabilities": {
                "alwaysMatch": {
                    "platformName": "Android" if platform == "android" else "iOS",
                    **{f"appium:{k}" if not k.startswith("appium:") else k: v for k, v in appium_options.items()},
                },
                "firstMatch": [{}],
            }
        }
        value = self._call("POST", "/session", payload, timeout=self.session_timeout)
        if not isinstance(value, dict) or not value.get("sessionId"):
            raise RuntimeError("WebDriver session response did not contain sessionId")
        self.session_id = value["sessionId"]
        self.platform = platform
        return self.session_id

    def _session_path(self, suffix: str = "") -> str:
        if not self.session_id:
            raise RuntimeError("No active Appium session")
        return f"/session/{self.session_id}{suffix}"

    def stop_session(self) -> None:
        if self.session_id:
            self._call("DELETE", self._session_path())
            self.session_id = None

    def get_source(self) -> str:
        return str(self._call("GET", self._session_path("/source")))

    def get_screenshot(self) -> bytes:
        encoded = self._call("GET", self._session_path("/screenshot"))
        return base64.b64decode(encoded)

    def get_window_rect(self) -> dict[str, int]:
        value = self._call("GET", self._session_path("/window/rect"))
        return {key: int(value[key]) for key in ("x", "y", "width", "height")}

    def get_contexts(self) -> list[str]:
        value = self._call("GET", self._session_path("/contexts"))
        if not isinstance(value, list):
            raise RuntimeError("WebDriver contexts response was not a list")
        return [str(item) for item in value]

    def get_current_context(self) -> str:
        return str(self._call("GET", self._session_path("/context")))

    def get_current_app_id(self) -> str | None:
        raise NotImplementedError("Platform client must implement get_current_app_id")

    def switch_context(self, name: str) -> None:
        self._call("POST", self._session_path("/context"), {"name": name})

    def execute_script(self, script: str, arguments: list[dict] | None = None):
        return self._call(
            "POST",
            self._session_path("/execute/sync"),
            {"script": script, "args": arguments or []},
        )

    def open_deep_link(self, url: str, app_id: str) -> None:
        raise NotImplementedError("Platform client must implement open_deep_link")



    def tap_at(self, x: int, y: int) -> None:
        payload = {
            "actions": [
                {
                    "type": "pointer",
                    "id": "finger",
                    "parameters": {"pointerType": "touch"},
                    "actions": [
                        {"type": "pointerMove", "duration": 0, "x": int(x), "y": int(y)},
                        {"type": "pointerDown", "button": 0},
                        {"type": "pointerUp", "button": 0},
                    ],
                }
            ]
        }
        self._call("POST", self._session_path("/actions"), payload)

    def back(self) -> None:
        self._call("POST", self._session_path("/back"), {})

    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        *,
        duration_ms: int = 350,
    ) -> None:
        payload = {
            "actions": [
                {
                    "type": "pointer",
                    "id": "finger",
                    "parameters": {"pointerType": "touch"},
                    "actions": [
                        {"type": "pointerMove", "duration": 0, "x": int(start_x), "y": int(start_y)},
                        {"type": "pointerDown", "button": 0},
                        {
                            "type": "pointerMove",
                            "duration": int(duration_ms),
                            "x": int(end_x),
                            "y": int(end_y),
                        },
                        {"type": "pointerUp", "button": 0},
                    ],
                }
            ]
        }
        self._call("POST", self._session_path("/actions"), payload)

    def capture_screen(self, out_dir: str | Path, screen_id: str, state_id: str = "default") -> ScreenEvidence:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        source = self.get_source()
        screenshot_bytes = self.get_screenshot()
        rect = self.get_window_rect()
        screenshot_path = out / f"{screen_id}__{state_id}.png"
        source_path = out / f"{screen_id}__{state_id}.xml"
        screenshot_path.write_bytes(screenshot_bytes)
        source_path.write_text(source, encoding="utf-8")
        return ScreenEvidence(
            screen_id=screen_id,
            state_id=state_id,
            width=rect["width"],
            height=rect["height"],
            screenshot_path=str(screenshot_path),
            screenshot_sha256=sha256_file(screenshot_path),
            ui_tree_path=str(source_path),
            elements=parse_ui_tree(source),
            interactions=[],
        )
