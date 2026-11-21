from __future__ import annotations

from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Callable, Protocol

from .evidence import AppEvidence, FlowEvidence, FlowStepEvidence, InteractionEvidence, ScreenEvidence


_DEFAULT_DENY_TERMS = (
    "back",
    "返回",
    "allow",
    "允许",
    "允許",
    "authorize",
    "authorise",
    "delete",
    "remove",
    "erase",
    "purchase",
    "buy now",
    "place order",
    "checkout",
    "pay now",
    "submit",
    "save",
    "publish",
    "post",
    "send",
    "edit",
    "modify",
    "reorder",
    "hide",
    "add price",
    "confirm",
    "yes",
    "okay",
    "ok",
    "very important",
    "not important",
    "mandatory",
    "sign in",
    "log in",
    "login",
    "sign out",
    "log out",
    "logout",
    "allow access",
    "grant access",
    # Simplified/Traditional Chinese high-risk write/account/authorization actions.
    "删除", "刪除", "移除", "清除账户", "清除帳戶",
    "购买", "購買", "立即购买", "立即購買", "下单", "下單", "结账", "結帳",
    "付款", "支付", "提交", "保存", "儲存", "发布", "發佈", "發表", "发送", "傳送",
    "编辑", "編輯", "修改", "重新排序", "隐藏", "隱藏", "新增价格", "新增價格",
    "确认付款", "確認付款", "确定", "確定", "是", "重要", "非常重要的", "不重要", "强制性的", "強制性的",
    "向上", "向下", "null",
    "登录", "登入", "登出", "注销", "註銷",
    "授权", "授權", "允许访问", "允許存取", "允许权限", "允許權限",
)
DEFAULT_DENY_TERMS = _DEFAULT_DENY_TERMS
_SAFE_TAP_ROLES = {"button", "listitem", "switch"}
_EXACT_DENY_TERMS = {
    "yes", "okay", "ok", "确定", "確定", "是",
    "重要", "非常重要的", "不重要", "强制性的", "強制性的", "向上", "向下", "null",
}


class NavigationOutsideTargetApp(RuntimeError):
    def __init__(self, expected_app_id: str, current_app_id: str):
        self.expected_app_id = expected_app_id
        self.current_app_id = current_app_id
        super().__init__(
            f"navigation moved outside target app: expected {expected_app_id}, got {current_app_id}"
        )


def _label_is_blocked(label: str, normalized_deny_terms: tuple[str, ...]) -> bool:
    normalized_label = label.casefold().strip()
    label_tokens = normalized_label.split()
    return any(
        (normalized_label == term or term in label_tokens)
        if term in _EXACT_DENY_TERMS
        else term in normalized_label
        for term in normalized_deny_terms
    )


def build_interaction_coverage(
    app: AppEvidence,
    *,
    deny_terms: tuple[str, ...] = _DEFAULT_DENY_TERMS,
    previously_verified_control_keys: set[str] | frozenset[str] = frozenset(),
    previously_verified_controls: tuple[dict[str, object], ...] | list[dict[str, object]] = (),
) -> dict[str, object]:
    """Report every discovered actionable control and whether it was verified."""
    normalized_deny_terms = tuple(term.casefold() for term in deny_terms)
    controls: list[dict[str, object]] = []

    screen_keys = {
        screen.screen_id: _screen_control_context_key(screen)
        for screen in app.screens
    }
    for screen in app.screens:
        attempted = {
            interaction.target_element_id: interaction
            for interaction in screen.interactions
            if interaction.kind == "tap" and interaction.target_element_id
        }
        external_blocks = {
            interaction.target_element_id: interaction
            for interaction in screen.interactions
            if interaction.kind == "blocked_external" and interaction.target_element_id
        }
        for element in screen.elements:
            if (
                not element.visible
                or not element.enabled
                or element.role.lower() not in _SAFE_TAP_ROLES
                or element.bounds.width <= 0
                or element.bounds.height <= 0
            ):
                continue
            label = " ".join(
                part for part in (element.text, element.accessibility_id) if part
            ).strip()
            if not label:
                continue
            interaction = attempted.get(element.evidence_id)
            external_block = external_blocks.get(element.evidence_id)
            control_key = _control_key(screen, element)
            resume_keys = _control_resume_keys(screen, element)
            blocked = _label_is_blocked(label, normalized_deny_terms)
            if interaction is not None:
                status = "VERIFIED"
                verification_source = "current_run"
            elif external_block is not None:
                status = "BLOCKED_EXTERNAL_APP"
                verification_source = "current_run"
            elif (
                any(key in previously_verified_control_keys for key in resume_keys)
                or _matches_resume_records(screen, element, previously_verified_controls)
            ):
                status = "VERIFIED"
                verification_source = "previous_run"
            elif blocked:
                status = "BLOCKED_BY_POLICY"
                verification_source = None
            else:
                status = "UNVERIFIED"
                verification_source = None
            controls.append(
                {
                    "screen_id": screen.screen_id,
                    "screen_key": screen_keys[screen.screen_id],
                    "element_id": element.evidence_id,
                    "control_key": control_key,
                    "resume_keys": resume_keys,
                    "label": label,
                    "role": element.role,
                    "status": status,
                    "verification_source": verification_source,
                    "result_screen_id": (
                        interaction.result_screen_id
                        if interaction
                        else external_block.result_screen_id if external_block else None
                    ),
                    "result_screen_key": (
                        screen_keys.get(interaction.result_screen_id)
                        if interaction and interaction.result_screen_id
                        else None
                    ),
                }
            )

    key_counts = Counter(
        resume_key
        for item in controls
        for resume_key in item["resume_keys"]
    )
    for item in controls:
        item["unique_resume_keys"] = [
            key for key in item["resume_keys"]
            if key_counts[key] == 1
        ]
        item["resume_eligible"] = bool(item["unique_resume_keys"])

    verified = sum(item["status"] == "VERIFIED" for item in controls)
    blocked = sum(str(item["status"]).startswith("BLOCKED_") for item in controls)
    unverified = sum(item["status"] == "UNVERIFIED" for item in controls)
    complete = bool(controls) and verified == len(controls)
    return {
        "status": "COMPLETE" if complete else "INCOMPLETE",
        "total_controls": len(controls),
        "verified_controls": verified,
        "blocked_controls": blocked,
        "unverified_controls": unverified,
        "controls": controls,
    }


def build_resume_records(app: AppEvidence) -> list[dict[str, object]]:
    """Extract verified control descriptors that can be matched in a later capture run."""
    records: list[dict[str, object]] = []
    for screen in app.screens:
        attempted = {
            interaction.target_element_id: interaction
            for interaction in screen.interactions
            if interaction.kind == "tap" and interaction.target_element_id
        }
        for element in screen.elements:
            interaction = attempted.get(element.evidence_id)
            if interaction is None:
                continue
            records.append(
                {
                    "identity_key": _resume_identity_key(element),
                    "screen_size": [screen.width, screen.height],
                    "screen_features": sorted(_screen_feature_tokens(screen)),
                    "terminal": interaction.result_screen_id in {None, screen.screen_id},
                }
            )
    return records


class ExplorerClient(Protocol):
    def capture_screen(self, out_dir: str | Path, screen_id: str, state_id: str = "default") -> ScreenEvidence: ...

    def tap_at(self, x: int, y: int) -> None: ...

    def back(self) -> None: ...

    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        *,
        duration_ms: int = 350,
    ) -> None: ...


def _screen_signature(screen: ScreenEvidence) -> str:
    if not screen.elements:
        return screen.screenshot_sha256
    payload = [
        {
            "role": item.role.lower(),
            "text": (item.text or "").strip().lower(),
            "accessibility_id": item.accessibility_id or "",
            "bounds": [item.bounds.x, item.bounds.y, item.bounds.width, item.bounds.height],
            "enabled": item.enabled,
            "selected": item.selected,
            "visible": item.visible,
            "parent_id": item.parent_id or "",
        }
        for item in screen.elements
        if item.visible
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _screen_feature_tokens(screen: ScreenEvidence) -> set[str]:
    tokens: set[str] = set()
    for item in screen.elements:
        if not item.visible:
            continue
        payload = {
            "role": item.role.casefold(),
            "text": (item.text or "").strip().casefold(),
            "accessibility_id": (item.accessibility_id or "").strip(),
            "bounds": [item.bounds.x, item.bounds.y, item.bounds.width, item.bounds.height],
            "selected": item.selected,
        }
        tokens.add(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return tokens


def _resume_identity_key(element) -> str:
    payload = {
        "role": element.role.casefold(),
        "text": (element.text or "").strip().casefold(),
        "accessibility_id": (element.accessibility_id or "").strip(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _matches_resume_records(
    screen: ScreenEvidence,
    element,
    records: tuple[dict[str, object], ...] | list[dict[str, object]],
    *,
    minimum_containment: float = 0.8,
) -> bool:
    if not records:
        return False
    identity_key = _resume_identity_key(element)
    current_features = _screen_feature_tokens(screen)
    for record in records:
        if record.get("identity_key") != identity_key:
            continue
        if record.get("screen_size") != [screen.width, screen.height]:
            continue
        previous_features = set(record.get("screen_features", []))
        smaller = min(len(current_features), len(previous_features))
        if smaller == 0:
            continue
        containment = len(current_features & previous_features) / smaller
        if containment >= minimum_containment:
            return True
    return False


def _screen_control_context_key(screen: ScreenEvidence) -> str:
    """Stable screen identity for resume reports; excludes run-local IDs and screenshots."""
    payload = {
        "size": [screen.width, screen.height],
        "elements": [
            {
                "role": item.role.casefold(),
                "text": (item.text or "").strip().casefold(),
                "accessibility_id": (item.accessibility_id or "").strip(),
                "bounds": [item.bounds.x, item.bounds.y, item.bounds.width, item.bounds.height],
            }
            for item in screen.elements
            if item.visible
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _control_key(screen: ScreenEvidence, element) -> str:
    payload = {
        "viewport": [screen.width, screen.height],
        "role": element.role.casefold(),
        "text": (element.text or "").strip().casefold(),
        "accessibility_id": (element.accessibility_id or "").strip(),
        "bounds": [element.bounds.x, element.bounds.y, element.bounds.width, element.bounds.height],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _control_resume_keys(screen: ScreenEvidence, element) -> list[str]:
    """Return redundant identities so one unrelated dynamic element cannot break resume."""
    local_key = _control_key(screen, element)
    keys = {local_key}
    for anchor in screen.elements:
        if anchor.evidence_id == element.evidence_id or not anchor.visible:
            continue
        anchor_label = " ".join(
            part for part in (anchor.text, anchor.accessibility_id) if part
        ).strip().casefold()
        if not anchor_label:
            continue
        payload = {
            "control": local_key,
            "anchor": {
                "role": anchor.role.casefold(),
                "label": anchor_label,
                "bounds": [
                    anchor.bounds.x,
                    anchor.bounds.y,
                    anchor.bounds.width,
                    anchor.bounds.height,
                ],
            },
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        keys.add(sha256(canonical.encode("utf-8")).hexdigest())
    return sorted(keys)


def _element_locator(element) -> dict[str, object]:
    """Build a semantic locator that can be resolved again after a fresh capture."""
    return {
        "role": element.role.casefold(),
        "text": (element.text or "").strip().casefold(),
        "accessibility_id": (element.accessibility_id or "").strip(),
        "center": [
            element.bounds.x + element.bounds.width / 2,
            element.bounds.y + element.bounds.height / 2,
        ],
    }


def _resolve_locator(screen: ScreenEvidence, locator: dict[str, object]):
    matches = [
        element
        for element in screen.elements
        if element.visible
        and element.enabled
        and element.bounds.width > 0
        and element.bounds.height > 0
        and element.role.casefold() == locator["role"]
        and (element.text or "").strip().casefold() == locator["text"]
        and (element.accessibility_id or "").strip() == locator["accessibility_id"]
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    target_x, target_y = locator["center"]
    ranked = sorted(
        (
            (
                (element.bounds.x + element.bounds.width / 2 - target_x) ** 2
                + (element.bounds.y + element.bounds.height / 2 - target_y) ** 2,
                element,
            )
            for element in matches
        ),
        key=lambda item: item[0],
    )
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]


class SafeStateExplorer:
    def __init__(
        self,
        client: ExplorerClient,
        *,
        settle_seconds: float = 0.6,
        sleep_fn: Callable[[float], None] = time.sleep,
        deny_terms: tuple[str, ...] = _DEFAULT_DENY_TERMS,
        restore_callback: Callable[[], None] | None = None,
        skip_control_keys: set[str] | frozenset[str] = frozenset(),
        skip_resume_records: tuple[dict[str, object], ...] | list[dict[str, object]] = (),
        progress_callback: Callable[[AppEvidence], None] | None = None,
        progress_every: int = 10,
    ):
        if progress_every < 1:
            raise ValueError("progress_every must be >= 1")
        self.client = client
        self.settle_seconds = max(0.0, settle_seconds)
        self.sleep_fn = sleep_fn
        self.deny_terms = tuple(term.casefold() for term in deny_terms)
        self.restore_callback = restore_callback
        self.skip_control_keys = frozenset(skip_control_keys)
        self.skip_resume_records = tuple(skip_resume_records)
        self.progress_callback = progress_callback
        self.progress_every = progress_every

    def _settle(self) -> None:
        if self.settle_seconds:
            self.sleep_fn(self.settle_seconds)

    def _safe_tap_candidates(self, screen: ScreenEvidence):
        candidates = []
        for element in screen.elements:
            if not element.visible or not element.enabled or element.role.lower() not in _SAFE_TAP_ROLES:
                continue
            if element.bounds.width <= 0 or element.bounds.height <= 0:
                continue
            label = " ".join(part for part in (element.text, element.accessibility_id) if part).strip().casefold()
            if not label:
                continue
            if _label_is_blocked(label, self.deny_terms):
                continue
            if any(key in self.skip_control_keys for key in _control_resume_keys(screen, element)):
                continue
            if _matches_resume_records(screen, element, self.skip_resume_records):
                continue
            candidates.append(element)
        return sorted(candidates, key=lambda item: (item.bounds.y, item.bounds.x, item.evidence_id))

    def explore(
        self,
        *,
        app_id: str,
        app_name: str,
        platform: str,
        app_version: str | None,
        out_dir: str | Path,
        capture_source: str = "appium",
        max_screens: int = 30,
        max_depth: int = 3,
        max_actions_per_screen: int = 6,
        max_scrolls_per_screen: int = 1,
    ) -> AppEvidence:
        if max_screens < 1:
            raise ValueError("max_screens must be >= 1")
        if min(max_depth, max_actions_per_screen, max_scrolls_per_screen) < 0:
            raise ValueError("exploration limits must be >= 0")

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        by_signature: dict[str, str] = {}
        screens: dict[str, ScreenEvidence] = {}
        flow_steps: list[FlowStepEvidence] = []
        capture_counter = 0
        root_screen_id: str | None = None
        last_progress_count = -1

        def capture_current() -> tuple[ScreenEvidence | None, bool]:
            nonlocal capture_counter
            current_app_reader = getattr(self.client, "get_current_app_id", None)
            if callable(current_app_reader):
                current_app_id = current_app_reader()
                if current_app_id and current_app_id != app_id:
                    raise NavigationOutsideTargetApp(app_id, current_app_id)
            capture_counter += 1
            raw = self.client.capture_screen(
                out,
                screen_id=f"screen-{capture_counter:04d}",
                state_id="default",
            )
            signature = _screen_signature(raw)
            existing_id = by_signature.get(signature)
            if existing_id is not None:
                return screens[existing_id], False
            if len(screens) >= max_screens:
                return None, False
            by_signature[signature] = raw.screen_id
            screens[raw.screen_id] = raw
            return raw, True

        def current_app_evidence() -> AppEvidence:
            if root_screen_id is None:
                raise RuntimeError("Cannot build progress evidence before the root screen exists")
            return AppEvidence(
                app_id=app_id,
                app_name=app_name,
                platform=platform,
                app_version=app_version,
                capture_source=capture_source,
                screens=list(screens.values()),
                flows=[FlowEvidence(
                    flow_id="flow-discovered-001",
                    name="Safe discovered flow",
                    start_screen_id=root_screen_id,
                    steps=list(flow_steps),
                )],
            )

        def emit_progress(*, force: bool = False) -> None:
            nonlocal last_progress_count
            if self.progress_callback is None or root_screen_id is None:
                return
            step_count = len(flow_steps)
            if not force and step_count % self.progress_every != 0:
                return
            if step_count == last_progress_count:
                return
            self.progress_callback(current_app_evidence())
            last_progress_count = step_count

        def record_transition(source: ScreenEvidence, interaction: InteractionEvidence, target: ScreenEvidence) -> None:
            if source.screen_id not in screens or target.screen_id not in screens:
                raise ValueError("Cannot record transition to an unregistered screen")
            source_current = screens[source.screen_id]
            screens[source.screen_id] = replace(
                source_current,
                interactions=[*source_current.interactions, interaction],
            )
            flow_steps.append(
                FlowStepEvidence(
                    source_screen_id=source.screen_id,
                    source_state_id=source.state_id,
                    interaction=interaction,
                    target_screen_id=target.screen_id,
                    target_state_id=target.state_id,
                )
            )
            emit_progress()

        def replay_path(
            path: tuple[dict[str, object], ...],
            source: ScreenEvidence,
            expected: ScreenEvidence,
        ) -> ScreenEvidence | None:
            """Restore the root and replay a checked path using freshly resolved controls."""
            if self.restore_callback is None:
                return None
            self.restore_callback()
            self._settle()
            recovered, _ = capture_current()
            if recovered is None:
                return None
            restore_interaction = InteractionEvidence(
                kind="restore",
                target_element_id=None,
                payload={"replay_path_length": len(path)},
                result_screen_id=recovered.screen_id,
                result_state_id=recovered.state_id,
            )
            record_transition(source, restore_interaction, recovered)

            for step in path:
                if step["kind"] == "tap":
                    element = _resolve_locator(recovered, step["locator"])
                    if element is None:
                        return None
                    x = element.bounds.x + element.bounds.width // 2
                    y = element.bounds.y + element.bounds.height // 2
                    self.client.tap_at(x, y)
                    payload = {"x": x, "y": y, "replay": True}
                    target_element_id = element.evidence_id
                else:
                    x = max(1, recovered.width // 2)
                    start_y = max(1, int(recovered.height * 0.78))
                    end_y = max(1, int(recovered.height * 0.30))
                    self.client.swipe(x, start_y, x, end_y, duration_ms=350)
                    payload = {
                        "direction": "up",
                        "start": {"x": x, "y": start_y},
                        "end": {"x": x, "y": end_y},
                        "replay": True,
                    }
                    target_element_id = None
                self._settle()
                replayed, _ = capture_current()
                if replayed is None or _screen_signature(replayed) != step["target_signature"]:
                    return None
                replay_interaction = InteractionEvidence(
                    kind=step["kind"],
                    target_element_id=target_element_id,
                    payload=payload,
                    result_screen_id=replayed.screen_id,
                    result_state_id=replayed.state_id,
                )
                record_transition(recovered, replay_interaction, replayed)
                recovered = replayed

            if _screen_signature(recovered) != _screen_signature(expected):
                return None
            return recovered

        def visit(
            current: ScreenEvidence,
            depth: int,
            scroll_budget: int,
            path: tuple[dict[str, object], ...],
        ) -> None:
            if depth >= max_depth or len(screens) >= max_screens:
                return

            candidate_locators = [
                _element_locator(element)
                for element in self._safe_tap_candidates(current)[:max_actions_per_screen]
            ]
            active_current = current
            for locator in candidate_locators:
                if len(screens) >= max_screens:
                    break
                element = _resolve_locator(active_current, locator)
                if element is None:
                    continue
                x = element.bounds.x + element.bounds.width // 2
                y = element.bounds.y + element.bounds.height // 2
                self.client.tap_at(x, y)
                self._settle()
                try:
                    target, is_new = capture_current()
                except NavigationOutsideTargetApp as exc:
                    blocked_interaction = InteractionEvidence(
                        kind="blocked_external",
                        target_element_id=element.evidence_id,
                        payload={"external_app_id": exc.current_app_id},
                        result_screen_id=active_current.screen_id,
                        result_state_id=active_current.state_id,
                    )
                    record_transition(active_current, blocked_interaction, active_current)
                    if self.restore_callback is None:
                        raise
                    restored = replay_path(path, active_current, current)
                    if restored is None:
                        return
                    active_current = restored
                    continue
                if target is None:
                    # We discovered a new state after the screen budget was exhausted. Restore the
                    # previous known state without persisting a dangling Flow reference.
                    self.client.back()
                    self._settle()
                    capture_current()
                    break
                interaction = InteractionEvidence(
                    kind="tap",
                    target_element_id=element.evidence_id,
                    payload={"x": x, "y": y},
                    result_screen_id=target.screen_id,
                    result_state_id=target.state_id,
                )
                record_transition(active_current, interaction, target)
                if is_new:
                    visit(
                        target,
                        depth + 1,
                        max_scrolls_per_screen,
                        (*path, {
                            "kind": "tap",
                            "locator": locator,
                            "target_signature": _screen_signature(target),
                        }),
                    )
                if target.screen_id != active_current.screen_id:
                    if self.restore_callback is not None:
                        restored = replay_path(path, target, current)
                        if restored is None:
                            return
                        active_current = restored
                        continue
                    self.client.back()
                    self._settle()
                    restored, _ = capture_current()
                    if restored is None:
                        return
                    restore_interaction = InteractionEvidence(
                        kind="back",
                        target_element_id=None,
                        payload={},
                        result_screen_id=restored.screen_id,
                        result_state_id=restored.state_id,
                    )
                    record_transition(target, restore_interaction, restored)
                    if restored.screen_id != current.screen_id:
                        return
                    active_current = restored

            if scroll_budget <= 0 or len(screens) >= max_screens:
                return

            x = max(1, current.width // 2)
            start_y = max(1, int(current.height * 0.78))
            end_y = max(1, int(current.height * 0.30))
            self.client.swipe(x, start_y, x, end_y, duration_ms=350)
            self._settle()
            target, is_new = capture_current()
            if target is None:
                self.client.swipe(x, end_y, x, start_y, duration_ms=350)
                self._settle()
                capture_current()
                return
            interaction = InteractionEvidence(
                kind="swipe",
                target_element_id=None,
                payload={
                    "direction": "up",
                    "start": {"x": x, "y": start_y},
                    "end": {"x": x, "y": end_y},
                },
                result_screen_id=target.screen_id,
                result_state_id=target.state_id,
            )
            record_transition(active_current, interaction, target)
            if is_new:
                visit(
                    target,
                    depth + 1,
                    scroll_budget - 1,
                    (*path, {
                        "kind": "swipe",
                        "target_signature": _screen_signature(target),
                    }),
                )
            if target.screen_id != active_current.screen_id:
                if self.restore_callback is not None:
                    replay_path(path, target, current)
                    return
                self.client.swipe(x, end_y, x, start_y, duration_ms=350)
                self._settle()
                restored, _ = capture_current()
                if restored is None:
                    return
                restore_interaction = InteractionEvidence(
                    kind="swipe",
                    target_element_id=None,
                    payload={
                        "direction": "down",
                        "start": {"x": x, "y": end_y},
                        "end": {"x": x, "y": start_y},
                    },
                    result_screen_id=restored.screen_id,
                    result_state_id=restored.state_id,
                )
                record_transition(target, restore_interaction, restored)
                if restored.screen_id != current.screen_id:
                    return

        root, _ = capture_current()
        if root is None:
            raise RuntimeError("Unable to capture initial screen")
        root_screen_id = root.screen_id
        emit_progress(force=True)
        visit(root, 0, max_scrolls_per_screen, ())
        app = current_app_evidence()
        emit_progress(force=True)
        return app
