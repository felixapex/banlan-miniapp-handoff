from dataclasses import replace
from pathlib import Path

import pytest

from collector_core.evidence import AppEvidence, Bounds, ElementEvidence, InteractionEvidence, ScreenEvidence
from collector_core.explorer import SafeStateExplorer, build_interaction_coverage, build_resume_records


def _element(evidence_id: str, text: str, y: int) -> ElementEvidence:
    return ElementEvidence(
        evidence_id=evidence_id,
        role="button",
        text=text,
        bounds=Bounds(x=20, y=y, width=160, height=44),
        enabled=True,
        selected=False,
        visible=True,
        accessibility_id=evidence_id,
        parent_id=None,
    )


class FakeAppiumClient:
    def __init__(self):
        self.state = "home"
        self.destructive_tapped = False
        self.actions: list[tuple] = []

    def get_current_app_id(self) -> str:
        return "com.example"

    def capture_screen(self, out_dir: str | Path, screen_id: str, state_id: str = "default") -> ScreenEvidence:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        if self.state == "home":
            elements = [
                _element("details", "View details", 100),
                _element("delete", "Delete account", 180),
            ]
        elif self.state == "home_scrolled":
            elements = [_element("settings", "Settings", 500)]
        else:
            elements = [_element("back-label", "Details", 100)]
        return ScreenEvidence(
            screen_id=screen_id,
            state_id=state_id,
            width=390,
            height=844,
            screenshot_path=str(Path(out_dir) / f"{screen_id}.png"),
            screenshot_sha256=f"sha-{self.state}",
            ui_tree_path=None,
            elements=elements,
            interactions=[],
        )

    def tap_at(self, x: int, y: int) -> None:
        self.actions.append(("tap", x, y, self.state))
        if self.state == "home" and y == 202:
            self.destructive_tapped = True
        elif self.state == "home" and y == 122:
            self.state = "details"
        elif self.state == "home_scrolled" and y == 522:
            self.state = "details"

    def back(self) -> None:
        self.actions.append(("back", self.state))
        if self.state == "details":
            self.state = "home"

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, *, duration_ms: int = 350) -> None:
        self.actions.append(("swipe", start_y, end_y, self.state))
        if self.state == "home" and start_y > end_y:
            self.state = "home_scrolled"
        elif self.state == "home_scrolled" and start_y < end_y:
            self.state = "home"


def test_safe_state_explorer_discovers_tap_and_scroll_states_without_destructive_actions(tmp_path: Path):
    client = FakeAppiumClient()
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)

    app = explorer.explore(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version="1.0",
        out_dir=tmp_path,
        max_screens=5,
        max_depth=1,
        max_actions_per_screen=3,
        max_scrolls_per_screen=1,
    )

    hashes = {screen.screenshot_sha256 for screen in app.screens}
    assert "sha-home" in hashes
    assert "sha-details" in hashes
    assert "sha-home_scrolled" in hashes
    assert client.destructive_tapped is False
    assert len(app.flows) == 1
    kinds = [step.interaction.kind for step in app.flows[0].steps]
    assert "tap" in kinds
    assert "swipe" in kinds
    assert any(screen.interactions for screen in app.screens)


def test_safe_state_explorer_honors_screen_limit(tmp_path: Path):
    client = FakeAppiumClient()
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)
    app = explorer.explore(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version=None,
        out_dir=tmp_path,
        max_screens=2,
        max_depth=3,
        max_actions_per_screen=5,
        max_scrolls_per_screen=2,
    )
    assert len(app.screens) <= 2


def test_safe_state_explorer_skips_unlabeled_interactive_elements():
    client = FakeAppiumClient()
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)
    screen = ScreenEvidence(
        screen_id="s1", state_id="default", width=390, height=844,
        screenshot_path="s1.png", screenshot_sha256="sha", ui_tree_path=None,
        elements=[ElementEvidence(
            evidence_id="anonymous", role="button", text=None,
            bounds=Bounds(x=20, y=100, width=44, height=44),
            enabled=True, selected=False, visible=True, accessibility_id=None, parent_id=None,
        )], interactions=[],
    )
    assert explorer._safe_tap_candidates(screen) == []


def test_safe_state_explorer_records_restoration_back_in_replay_trace(tmp_path: Path):
    client = FakeAppiumClient()
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)
    app = explorer.explore(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version="1.0",
        out_dir=tmp_path,
        max_screens=5,
        max_depth=1,
        max_actions_per_screen=1,
        max_scrolls_per_screen=0,
    )

    steps = app.flows[0].steps
    assert [step.interaction.kind for step in steps] == ["tap", "back"]
    assert steps[0].source_screen_id != steps[0].target_screen_id
    assert steps[1].source_screen_id == steps[0].target_screen_id
    assert steps[1].target_screen_id == steps[0].source_screen_id


def test_safe_state_explorer_emits_valid_incremental_checkpoints(tmp_path: Path):
    from collector_core.evidence import validate_evidence_graph

    checkpoints = []
    client = FakeAppiumClient()
    explorer = SafeStateExplorer(
        client,
        settle_seconds=0,
        sleep_fn=lambda _seconds: None,
        progress_callback=checkpoints.append,
        progress_every=2,
    )

    explorer.explore(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version="1.0",
        out_dir=tmp_path,
        max_screens=5,
        max_depth=1,
        max_actions_per_screen=1,
        max_scrolls_per_screen=0,
    )

    assert checkpoints
    validate_evidence_graph(checkpoints[-1])
    assert len(checkpoints[-1].flows[0].steps) == 2


def test_safe_state_explorer_checkpoints_root_before_first_action_can_fail(tmp_path: Path):
    from collector_core.evidence import validate_evidence_graph

    class EarlyFailureClient(FakeAppiumClient):
        def __init__(self):
            super().__init__()
            self.capture_calls = 0

        def capture_screen(self, out_dir, screen_id, state_id="default"):
            self.capture_calls += 1
            if self.capture_calls > 1:
                raise TimeoutError("simulated Appium read timeout")
            return super().capture_screen(out_dir, screen_id, state_id)

    checkpoints = []
    explorer = SafeStateExplorer(
        EarlyFailureClient(),
        settle_seconds=0,
        sleep_fn=lambda _seconds: None,
        progress_callback=checkpoints.append,
        progress_every=10,
    )

    with pytest.raises(TimeoutError, match="simulated Appium read timeout"):
        explorer.explore(
            app_id="com.example",
            app_name="Example",
            platform="android",
            app_version="1.0",
            out_dir=tmp_path,
            max_screens=5,
            max_depth=1,
            max_actions_per_screen=1,
            max_scrolls_per_screen=0,
        )

    assert len(checkpoints) == 1
    validate_evidence_graph(checkpoints[0])
    assert len(checkpoints[0].screens) == 1
    assert checkpoints[0].flows[0].steps == []


def test_safe_state_explorer_records_reverse_swipe_restoration_in_replay_trace(tmp_path: Path):
    client = FakeAppiumClient()
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)
    app = explorer.explore(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version="1.0",
        out_dir=tmp_path,
        max_screens=5,
        max_depth=1,
        max_actions_per_screen=0,
        max_scrolls_per_screen=1,
    )

    steps = app.flows[0].steps
    assert [step.interaction.kind for step in steps] == ["swipe", "swipe"]
    assert steps[0].interaction.payload["direction"] == "up"
    assert steps[1].interaction.payload["direction"] == "down"
    assert steps[1].source_screen_id == steps[0].target_screen_id
    assert steps[1].target_screen_id == steps[0].source_screen_id


def test_safe_state_explorer_never_emits_flow_reference_to_screen_beyond_limit(tmp_path: Path):
    from collector_core.evidence import validate_evidence_graph

    client = FakeAppiumClient()
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)
    app = explorer.explore(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version=None,
        out_dir=tmp_path,
        max_screens=1,
        max_depth=3,
        max_actions_per_screen=5,
        max_scrolls_per_screen=2,
    )
    validate_evidence_graph(app)
    known = {screen.screen_id for screen in app.screens}
    assert all(
        step.source_screen_id in known and step.target_screen_id in known
        for flow in app.flows
        for step in flow.steps
    )


def test_safe_state_explorer_denies_chinese_destructive_action(tmp_path: Path):
    client = FakeAppiumClient()
    # The fixture exposes the same home screen controls; inject a high-risk Chinese label
    # and assert the explorer never taps its center.
    original_capture = client.capture_screen

    def capture_with_destructive(out_dir, screen_id, state_id='default'):
        screen = original_capture(out_dir, screen_id, state_id)
        if screen.elements:
            first = screen.elements[0]
            screen.elements[0] = replace(first, text='删除账户', accessibility_id='删除账户')
        return screen

    client.capture_screen = capture_with_destructive
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)
    explorer.explore(
        app_id='com.example', app_name='Example', platform='android', app_version=None,
        out_dir=tmp_path, max_screens=3, max_depth=1, max_actions_per_screen=5, max_scrolls_per_screen=0,
    )
    # If the destructive control were considered safe, the first tap would target it.
    assert not any(action[0] == 'tap' for action in client.actions)


def test_safe_state_explorer_does_not_tap_system_back_control():
    client = FakeAppiumClient()
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)
    screen = replace(
        client.capture_screen(".", "home"),
        elements=[_element("back", "返回", 20), _element("details", "查看详情", 100)],
    )

    candidates = explorer._safe_tap_candidates(screen)

    assert [item.evidence_id for item in candidates] == ["details"]


def test_safe_state_explorer_blocks_affirmative_confirmation_but_allows_cancel():
    client = FakeAppiumClient()
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)
    screen = replace(
        client.capture_screen(".", "confirm"),
        elements=[
            _element("yes-cn", "是", 20),
            _element("yes-en", "Yes", 80),
            _element("confirm-cn", "确定", 140),
            _element("no-cn", "否", 200),
            _element("close-cn", "关闭", 260),
        ],
    )

    candidates = explorer._safe_tap_candidates(screen)

    assert [item.evidence_id for item in candidates] == ["no-cn", "close-cn"]


def test_safe_state_explorer_blocks_preference_value_choices():
    client = FakeAppiumClient()
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)
    screen = replace(
        client.capture_screen(".", "preferences"),
        elements=[
            _element("very-important", "非常重要的", 20),
            _element("not-important", "不重要", 80),
            _element("mandatory", "强制性的", 140),
            _element("important", "重要", 200),
            _element("health", "健康", 260),
        ],
    )

    candidates = explorer._safe_tap_candidates(screen)

    assert [item.evidence_id for item in candidates] == ["health"]


def test_safe_state_explorer_blocks_edit_reorder_and_add_price_actions():
    client = FakeAppiumClient()
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)
    screen = replace(
        client.capture_screen(".", "actions"),
        elements=[
            _element("edit", "編輯產品", 20),
            _element("reorder", "重新排序或隱藏操作", 80),
            _element("add-price", "新增價格", 140),
            _element("move-up", "向上", 200),
            _element("move-down", "向下", 260),
            _element("invalid", "null", 320),
            _element("alternatives", "尋找替代方案", 380),
        ],
    )

    candidates = explorer._safe_tap_candidates(screen)

    assert [item.evidence_id for item in candidates] == ["alternatives"]


def test_safe_state_explorer_fails_closed_if_navigation_leaves_target_app(tmp_path: Path):
    class LeavingClient(FakeAppiumClient):
        def __init__(self):
            super().__init__()
            self.current_app_id = "com.example"

        def get_current_app_id(self) -> str:
            return self.current_app_id

        def tap_at(self, x: int, y: int) -> None:
            super().tap_at(x, y)
            self.current_app_id = "org.other"

    client = LeavingClient()
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)

    with pytest.raises(RuntimeError, match="outside target app"):
        explorer.explore(
            app_id="com.example",
            app_name="Example",
            platform="android",
            app_version=None,
            out_dir=tmp_path,
            max_screens=3,
            max_depth=1,
            max_actions_per_screen=1,
            max_scrolls_per_screen=0,
        )


def test_safe_state_explorer_records_external_app_block_and_continues_after_restore(tmp_path: Path):
    class ExternalThenSafeClient(FakeAppiumClient):
        def __init__(self):
            super().__init__()
            self.current_app_id = "com.example"

        def get_current_app_id(self) -> str:
            return self.current_app_id

        def capture_screen(self, out_dir, screen_id, state_id="default"):
            screen = super().capture_screen(out_dir, screen_id, state_id)
            if self.state == "home":
                screen = replace(
                    screen,
                    elements=[
                        _element("external", "Learn more", 100),
                        _element("details", "View details", 180),
                    ],
                )
            return screen

        def tap_at(self, x: int, y: int) -> None:
            self.actions.append(("tap", x, y, self.state))
            if self.state == "home" and y == 122:
                self.current_app_id = "org.browser"
            elif self.state == "home" and y == 202:
                self.state = "details"

    client = ExternalThenSafeClient()

    def restore_root() -> None:
        client.actions.append(("restore", client.state))
        client.current_app_id = "com.example"
        client.state = "home"

    explorer = SafeStateExplorer(
        client,
        settle_seconds=0,
        sleep_fn=lambda _seconds: None,
        restore_callback=restore_root,
    )
    app = explorer.explore(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version=None,
        out_dir=tmp_path,
        max_screens=6,
        max_depth=1,
        max_actions_per_screen=2,
        max_scrolls_per_screen=0,
    )

    report = build_interaction_coverage(app)
    statuses = {item["label"]: item["status"] for item in report["controls"]}
    assert statuses["Learn more external"] == "BLOCKED_EXTERNAL_APP"
    assert statuses["View details details"] == "VERIFIED"
    assert [action[0] for action in client.actions].count("tap") == 2


def test_safe_state_explorer_stops_branch_when_back_does_not_restore_source(tmp_path: Path):
    class RestoreMismatchClient(FakeAppiumClient):
        def capture_screen(self, out_dir, screen_id, state_id="default"):
            screen = super().capture_screen(out_dir, screen_id, state_id)
            if self.state == "home":
                screen.elements[1] = _element("settings", "设置", 180)
            return screen

        def back(self) -> None:
            self.actions.append(("back", self.state))
            self.state = "wrong-home"

    client = RestoreMismatchClient()
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)

    explorer.explore(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version=None,
        out_dir=tmp_path,
        max_screens=5,
        max_depth=1,
        max_actions_per_screen=2,
        max_scrolls_per_screen=0,
    )

    assert [action[0] for action in client.actions].count("tap") == 1


def test_safe_state_explorer_uses_restore_callback_before_continuing(tmp_path: Path):
    class RestoreMismatchClient(FakeAppiumClient):
        def capture_screen(self, out_dir, screen_id, state_id="default"):
            screen = super().capture_screen(out_dir, screen_id, state_id)
            if self.state == "home":
                screen.elements[1] = _element("settings", "设置", 180)
            return screen

        def back(self) -> None:
            self.actions.append(("back", self.state))
            self.state = "wrong-home"

    client = RestoreMismatchClient()

    def restore_root() -> None:
        client.actions.append(("restore", client.state))
        client.state = "home"

    explorer = SafeStateExplorer(
        client,
        settle_seconds=0,
        sleep_fn=lambda _seconds: None,
        restore_callback=restore_root,
    )

    explorer.explore(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version=None,
        out_dir=tmp_path,
        max_screens=6,
        max_depth=1,
        max_actions_per_screen=2,
        max_scrolls_per_screen=0,
    )

    assert [action[0] for action in client.actions].count("tap") == 2
    assert [action[0] for action in client.actions].count("restore") == 1


def test_safe_state_explorer_replays_parent_path_before_next_nested_control(tmp_path: Path):
    """A broken Back must not make the explorer abandon sibling controls on a child page."""

    class NestedRestoreClient(FakeAppiumClient):
        def capture_screen(self, out_dir, screen_id, state_id="default"):
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            elements_by_state = {
                "home": [_element("products", "Products", 100)],
                "products": [
                    _element("product-a", "Product A", 100),
                    _element("product-b", "Product B", 180),
                ],
                "product-a": [_element("leaf-a", "Product A detail", 100)],
                "product-b": [_element("leaf-b", "Product B detail", 100)],
                "wrong": [_element("wrong", "Wrong page", 100)],
            }
            return ScreenEvidence(
                screen_id=screen_id,
                state_id=state_id,
                width=390,
                height=844,
                screenshot_path=str(Path(out_dir) / f"{screen_id}.png"),
                screenshot_sha256=f"sha-{self.state}",
                ui_tree_path=None,
                elements=elements_by_state[self.state],
                interactions=[],
            )

        def tap_at(self, x: int, y: int) -> None:
            self.actions.append(("tap", x, y, self.state))
            if self.state == "home" and y == 122:
                self.state = "products"
            elif self.state == "products" and y == 122:
                self.state = "product-a"
            elif self.state == "products" and y == 202:
                self.state = "product-b"

        def back(self) -> None:
            self.actions.append(("back", self.state))
            self.state = "wrong"

    client = NestedRestoreClient()

    def restore_root() -> None:
        client.actions.append(("restore", client.state))
        client.state = "home"

    explorer = SafeStateExplorer(
        client,
        settle_seconds=0,
        sleep_fn=lambda _seconds: None,
        restore_callback=restore_root,
    )

    explorer.explore(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version=None,
        out_dir=tmp_path,
        max_screens=12,
        max_depth=2,
        max_actions_per_screen=2,
        max_scrolls_per_screen=0,
    )

    nested_sources = [action[3] for action in client.actions if action[0] == "tap"]
    assert nested_sources.count("products") == 2


def test_interaction_coverage_lists_verified_blocked_and_unverified_controls():
    screen = ScreenEvidence(
        screen_id="home",
        state_id="default",
        width=390,
        height=844,
        screenshot_path="home.png",
        screenshot_sha256="sha",
        ui_tree_path=None,
        elements=[
            _element("details", "查看详情", 100),
            _element("delete", "删除账户", 180),
            _element("settings", "设置", 260),
        ],
        interactions=[InteractionEvidence(kind="tap", target_element_id="details")],
    )
    app = AppEvidence(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version=None,
        capture_source="appium",
        screens=[screen],
        flows=[],
    )

    report = build_interaction_coverage(app)

    assert report["status"] == "INCOMPLETE"
    assert report["total_controls"] == 3
    assert report["verified_controls"] == 1
    assert report["blocked_controls"] == 1
    assert report["unverified_controls"] == 1
    assert {item["status"] for item in report["controls"]} == {
        "VERIFIED",
        "BLOCKED_BY_POLICY",
        "UNVERIFIED",
    }


def test_interaction_coverage_control_key_is_stable_across_capture_run_ids():
    first = ScreenEvidence(
        screen_id="screen-0001",
        state_id="default",
        width=390,
        height=844,
        screenshot_path="first.png",
        screenshot_sha256="sha-first",
        ui_tree_path=None,
        elements=[_element("details-old-id", "查看详情", 100)],
        interactions=[],
    )
    second = replace(
        first,
        screen_id="screen-0099",
        screenshot_path="second.png",
        screenshot_sha256="sha-second",
        elements=[replace(
            _element("details-new-id", "查看详情", 100),
            accessibility_id="details-stable-accessibility-id",
        )],
    )
    first = replace(
        first,
        elements=[replace(first.elements[0], accessibility_id="details-stable-accessibility-id")],
    )

    def report_for(screen):
        return build_interaction_coverage(AppEvidence(
            app_id="com.example",
            app_name="Example",
            platform="android",
            app_version=None,
            capture_source="appium",
            screens=[screen],
            flows=[],
        ))

    assert report_for(first)["controls"][0]["control_key"] == report_for(second)["controls"][0]["control_key"]


def test_interaction_coverage_preserves_previous_verified_result_by_control_key():
    screen = ScreenEvidence(
        screen_id="new-run-screen",
        state_id="default",
        width=390,
        height=844,
        screenshot_path="new.png",
        screenshot_sha256="new-sha",
        ui_tree_path=None,
        elements=[_element("new-element-id", "查看详情", 100)],
        interactions=[],
    )
    app = AppEvidence(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version=None,
        capture_source="appium",
        screens=[screen],
        flows=[],
    )
    first_report = build_interaction_coverage(app)
    key = first_report["controls"][0]["control_key"]

    resumed = build_interaction_coverage(app, previously_verified_control_keys={key})

    assert resumed["controls"][0]["status"] == "VERIFIED"
    assert resumed["controls"][0]["verification_source"] == "previous_run"
    assert resumed["verified_controls"] == 1


def test_safe_state_explorer_skips_only_explicitly_resumed_terminal_control():
    client = FakeAppiumClient()
    screen = client.capture_screen(".", "home")
    report = build_interaction_coverage(AppEvidence(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version=None,
        capture_source="appium",
        screens=[screen],
        flows=[],
    ))
    details_key = next(item["control_key"] for item in report["controls"] if item["label"].startswith("View details"))

    explorer = SafeStateExplorer(
        client,
        settle_seconds=0,
        sleep_fn=lambda _seconds: None,
        skip_control_keys={details_key},
    )

    assert explorer._safe_tap_candidates(screen) == []


def test_interaction_coverage_marks_duplicate_local_control_keys_as_unsafe_to_resume():
    first = ScreenEvidence(
        screen_id="dialog-a",
        state_id="default",
        width=390,
        height=844,
        screenshot_path="a.png",
        screenshot_sha256="a",
        ui_tree_path=None,
        elements=[_element("close-a", "关闭", 100)],
        interactions=[],
    )
    second = replace(
        first,
        screen_id="dialog-b",
        screenshot_path="b.png",
        screenshot_sha256="b",
        elements=[replace(_element("close-b", "关闭", 100), accessibility_id="close-a")],
    )
    app = AppEvidence(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version=None,
        capture_source="appium",
        screens=[first, second],
        flows=[],
    )

    report = build_interaction_coverage(app)

    assert len({item["control_key"] for item in report["controls"]}) == 1
    assert all(item["resume_eligible"] is False for item in report["controls"])


def test_interaction_coverage_resume_identity_survives_unrelated_dynamic_control_change():
    target = replace(_element("target-old", "Health", 100), accessibility_id="health")
    old_screen = ScreenEvidence(
        screen_id="old",
        state_id="default",
        width=390,
        height=844,
        screenshot_path="old.png",
        screenshot_sha256="old",
        ui_tree_path=None,
        elements=[target, _element("dynamic", "Match", 180)],
        interactions=[],
    )
    new_screen = replace(
        old_screen,
        screen_id="new",
        screenshot_path="new.png",
        screenshot_sha256="new",
        elements=[
            replace(target, evidence_id="target-new"),
            replace(_element("dynamic", "Importance", 180), accessibility_id="dynamic"),
        ],
    )

    def target_report(screen):
        app = AppEvidence(
            app_id="com.example",
            app_name="Example",
            platform="android",
            app_version=None,
            capture_source="appium",
            screens=[screen],
            flows=[],
        )
        return build_interaction_coverage(app)["controls"][0]

    old_control = target_report(old_screen)
    new_control = target_report(new_screen)

    assert set(old_control["resume_keys"]) & set(new_control["resume_keys"])


def test_resume_records_match_same_page_with_small_dynamic_change_but_not_different_page():
    target = replace(_element("health-old", "Health", 100), accessibility_id="health")
    stable = [
        replace(_element(f"anchor-{index}", f"Anchor {index}", 140 + index * 40), role="text")
        for index in range(10)
    ]
    old_screen = ScreenEvidence(
        screen_id="old",
        state_id="default",
        width=390,
        height=844,
        screenshot_path="old.png",
        screenshot_sha256="old",
        ui_tree_path=None,
        elements=[target, *stable, _element("dynamic", "Match", 600)],
        interactions=[InteractionEvidence(
            kind="tap",
            target_element_id=target.evidence_id,
            result_screen_id="old",
            result_state_id="default",
        )],
    )
    old_app = AppEvidence(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version=None,
        capture_source="appium",
        screens=[old_screen],
        flows=[],
    )
    new_screen = replace(
        old_screen,
        screen_id="new",
        screenshot_path="new.png",
        screenshot_sha256="new",
        elements=[
            replace(target, evidence_id="health-new", bounds=replace(target.bounds, y=104)),
            *stable,
            replace(_element("dynamic", "Importance", 600), accessibility_id="dynamic"),
        ],
        interactions=[],
    )
    different_screen = replace(
        new_screen,
        screen_id="different",
        elements=[
            replace(target, evidence_id="health-different"),
            _element("unrelated", "Unrelated page", 300),
        ],
    )
    records = build_resume_records(old_app)

    def resumed_status(screen):
        app = replace(old_app, screens=[screen])
        return build_interaction_coverage(app, previously_verified_controls=records)["controls"][0]

    assert resumed_status(new_screen)["verification_source"] == "previous_run"
    assert resumed_status(different_screen)["status"] == "UNVERIFIED"


def test_safe_state_explorer_clicks_each_same_label_control_at_its_fresh_position(tmp_path: Path):
    class DuplicateLabelClient(FakeAppiumClient):
        def capture_screen(self, out_dir, screen_id, state_id="default"):
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            return ScreenEvidence(
                screen_id=screen_id,
                state_id=state_id,
                width=390,
                height=844,
                screenshot_path=str(Path(out_dir) / f"{screen_id}.png"),
                screenshot_sha256="same-screen",
                ui_tree_path=None,
                elements=[
                    replace(_element("option-1", "Option", 100), accessibility_id="option"),
                    replace(_element("option-2", "Option", 180), accessibility_id="option"),
                ],
                interactions=[],
            )

        def tap_at(self, x: int, y: int) -> None:
            self.actions.append(("tap", x, y, self.state))

    client = DuplicateLabelClient()
    explorer = SafeStateExplorer(client, settle_seconds=0, sleep_fn=lambda _seconds: None)

    explorer.explore(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version=None,
        out_dir=tmp_path,
        max_screens=3,
        max_depth=1,
        max_actions_per_screen=2,
        max_scrolls_per_screen=0,
    )

    assert [(action[1], action[2]) for action in client.actions if action[0] == "tap"] == [
        (100, 122),
        (100, 202),
    ]

