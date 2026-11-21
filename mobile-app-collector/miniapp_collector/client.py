from __future__ import annotations

from hashlib import sha256
import re
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit

from collector_core.evidence import ScreenEvidence
from collector_core.webdriver import parse_ui_tree


WECHAT_PACKAGE = "com.tencent.mm"
SHARE_LINK = re.compile(r"^#小程序://([^/\r\n]{1,100})/([A-Za-z0-9_-]{6,200})$")
_FOREGROUND_PACKAGE = re.compile(r"mCurrentFocus.*?\s([A-Za-z0-9_.]+)/")


def classify_miniapp_link(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("invalid miniapp link")
    if SHARE_LINK.fullmatch(value):
        return "wechat_share_text"
    url = urlsplit(value)
    if url.scheme == "weixin" and url.netloc == "dl" and url.path == "/business/" and url.query.startswith("t="):
        return "wechat_scheme"
    if url.scheme == "https" and url.hostname in {"wxaur.cn", "wxaurl.cn"} and url.path.strip("/"):
        return "wechat_url_link"
    raise ValueError("unsupported miniapp link")


class MiniappAdbClient:
    """ADB-backed WeChat mini-program client for a dedicated authorized test account."""

    def __init__(self, adb: str = "adb", *, target_id: str, serial: str | None = None):
        self.adb = str(adb)
        self.target_id = target_id
        self.serial = serial

    def _run(self, *args: str, timeout: float = 20) -> bytes:
        command = [self.adb]
        if self.serial:
            command.extend(["-s", self.serial])
        command.extend(args)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=timeout,
            creationflags=flags,
        )
        if result.returncode:
            details = result.stderr.decode("utf-8", "replace")[:500]
            raise RuntimeError(f"ADB command failed ({result.returncode}): {details}")
        return result.stdout

    def select(self) -> str:
        output = self._run("devices", "-l", timeout=10).decode("utf-8", "replace")
        devices = []
        for line in output.splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 2 and fields[1] == "device":
                devices.append(fields[0])
        if self.serial:
            if self.serial not in devices:
                raise RuntimeError(f"ADB device {self.serial} is not authorized and online")
        elif len(devices) == 1:
            self.serial = devices[0]
        else:
            raise RuntimeError(f"Expected one authorized Android device; found {len(devices)}")
        if not self._run("shell", "pm", "path", WECHAT_PACKAGE, timeout=10).strip():
            raise RuntimeError("WeChat is not installed on the selected Android device")
        return self.serial

    def foreground_package(self) -> str | None:
        raw = self._run("shell", "dumpsys", "window", "windows", timeout=10).decode(
            "utf-8", "replace"
        )
        match = _FOREGROUND_PACKAGE.search(raw)
        return match.group(1) if match else None

    def get_current_app_id(self) -> str | None:
        package = self.foreground_package()
        return self.target_id if package == WECHAT_PACKAGE else package

    def screenshot(self) -> bytes:
        data = self._run("exec-out", "screencap", "-p", timeout=20)
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("ADB screenshot is not a PNG")
        return data

    def hierarchy(self) -> bytes:
        remote = "/sdcard/Download/mobile-collector-miniapp.xml"
        for options in ((), ("--compressed",)):
            self._run("shell", "rm", "-f", remote, timeout=10)
            try:
                self._run("shell", "uiautomator", "dump", *options, remote, timeout=25)
                data = self._run("exec-out", "cat", remote, timeout=10)
                if b"<hierarchy" in data:
                    return data
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            finally:
                self._run("shell", "rm", "-f", remote, timeout=10)
        raise RuntimeError("Android UI hierarchy is unavailable")

    def tap_at(self, x: int, y: int) -> None:
        self._run("shell", "input", "tap", str(int(x)), str(int(y)), timeout=10)

    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        *,
        duration_ms: int = 350,
    ) -> None:
        self._run(
            "shell", "input", "swipe",
            str(int(start_x)), str(int(start_y)),
            str(int(end_x)), str(int(end_y)), str(int(duration_ms)),
            timeout=15,
        )

    def back(self) -> None:
        self._run("shell", "input", "keyevent", "KEYCODE_BACK", timeout=10)

    def input_ascii(self, value: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
            raise ValueError("ADB text input accepts only safe ASCII")
        self._run("shell", "input", "text", value, timeout=10)

    def _current_elements(self):
        return parse_ui_tree(self.hierarchy().decode("utf-8", "replace"))

    def _tap_unique(self, label: str) -> None:
        matches = [
            item for item in self._current_elements()
            if (item.text or "").strip() == label
            or (item.accessibility_id or "").strip() == label
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one '{label}' control; found {len(matches)}")
        item = matches[0]
        self.tap_at(
            item.bounds.x + item.bounds.width // 2,
            item.bounds.y + item.bounds.height // 2,
        )

    def _has_text(self, text: str) -> bool:
        return any(text in (item.text or "") for item in self._current_elements())

    def _open_share_text_in_self_chat(self, link: str) -> None:
        self._run(
            "shell", "am", "start", "-W",
            "-a", "android.intent.action.SEND",
            "-t", "text/plain",
            "--es", "android.intent.extra.TEXT", link,
            "-p", WECHAT_PACKAGE,
            timeout=20,
        )
        time.sleep(1)
        if self._has_text("账号状态异常"):
            raise RuntimeError("WeChat test account session is invalid; capture stopped")
        if self._has_text("分享方式"):
            self._tap_unique("发送给朋友")
            time.sleep(0.5)
            self._tap_unique("仅此一次")
            time.sleep(1)
        elif self._has_text("使用发送给朋友分享"):
            self._tap_unique("仅此一次")
            time.sleep(1)
        if self._has_text("选择一个聊天"):
            self._tap_unique("搜索")
            self.input_ascii("filehelper")
            time.sleep(1)
            if not self._has_text("微信号: filehelper"):
                raise RuntimeError("File Transfer Assistant ID was not confirmed")
        self._tap_unique("文件传输助手")
        time.sleep(1)
        if not self._has_text(link):
            raise RuntimeError("Exact mini-program share text was not confirmed")
        self._tap_unique("发送")
        time.sleep(1)
        if self._has_text("已发送"):
            self._tap_unique("留在微信")
            time.sleep(1)
        self._tap_unique(link)
        time.sleep(0.5)
        if self._has_text("即将打开"):
            self._tap_unique("允许")
        time.sleep(4)

    def open_miniapp_link(self, link: str, *, allow_share_text_input: bool = False) -> str:
        kind = classify_miniapp_link(link)
        if kind == "wechat_share_text":
            if not allow_share_text_input:
                raise RuntimeError("share-text opening requires --allow-share-text-input")
            self._open_share_text_in_self_chat(link)
            return kind
        self._run(
            "shell", "am", "start", "-W",
            "-a", "android.intent.action.VIEW",
            "-d", link,
            "-p", WECHAT_PACKAGE,
            timeout=20,
        )
        time.sleep(3)
        return kind

    def capture_screen(
        self,
        out_dir: str | Path,
        screen_id: str,
        state_id: str = "default",
    ) -> ScreenEvidence:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        screenshot = self.screenshot()
        hierarchy = self.hierarchy()
        if len(screenshot) < 24:
            raise RuntimeError("PNG screenshot header is incomplete")
        width = int.from_bytes(screenshot[16:20], "big")
        height = int.from_bytes(screenshot[20:24], "big")
        screenshot_path = out / f"{screen_id}__{state_id}.png"
        tree_path = out / f"{screen_id}__{state_id}.xml"
        screenshot_path.write_bytes(screenshot)
        tree_path.write_bytes(hierarchy)
        return ScreenEvidence(
            screen_id=screen_id,
            state_id=state_id,
            width=width,
            height=height,
            screenshot_path=str(screenshot_path),
            screenshot_sha256=sha256(screenshot).hexdigest(),
            ui_tree_path=str(tree_path),
            elements=parse_ui_tree(hierarchy.decode("utf-8", "replace")),
            interactions=[],
        )
