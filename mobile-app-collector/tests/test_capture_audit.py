import json
from pathlib import Path

from collector_core.capture_audit import audit_capture_bundle
from collector_core.evidence import AppEvidence, FlowEvidence, ScreenEvidence, save_evidence, sha256_file


def _write_bundle(tmp_path: Path) -> tuple[Path, Path, Path]:
    capture = tmp_path / "capture"
    capture.mkdir()
    screenshot = capture / "screen-0001__default.png"
    ui_tree = capture / "screen-0001__default.xml"
    screenshot.write_bytes(b"real-png-bytes")
    ui_tree.write_text("<hierarchy />", encoding="utf-8")
    screen = ScreenEvidence(
        screen_id="screen-0001",
        state_id="default",
        width=390,
        height=844,
        screenshot_path=str(screenshot),
        screenshot_sha256=sha256_file(screenshot),
        ui_tree_path=str(ui_tree),
        elements=[],
        interactions=[],
    )
    app = AppEvidence(
        app_id="com.example",
        app_name="Example",
        platform="android",
        app_version="1.0",
        capture_source="appium",
        screens=[screen],
        flows=[FlowEvidence(flow_id="flow-1", name="Flow", start_screen_id=screen.screen_id)],
    )
    evidence = tmp_path / "evidence.json"
    save_evidence(app, evidence)
    coverage = tmp_path / "interaction-coverage.json"
    coverage.write_text(json.dumps({
        "status": "INCOMPLETE",
        "total_controls": 2,
        "verified_controls": 1,
        "blocked_controls": 0,
        "unverified_controls": 1,
        "controls": [
            {"status": "VERIFIED"},
            {"status": "UNVERIFIED"},
        ],
    }), encoding="utf-8")
    return evidence, coverage, screenshot


def test_audit_capture_bundle_verifies_graph_assets_hashes_pairs_and_coverage(tmp_path: Path):
    evidence, coverage, _screenshot = _write_bundle(tmp_path)

    report = audit_capture_bundle(evidence, coverage)

    assert report["integrity_status"] == "PASS"
    assert report["coverage_status"] == "INCOMPLETE"
    assert report["screens"] == 1
    assert report["capture_png"] == 1
    assert report["capture_xml"] == 1
    assert report["missing_screenshots"] == []
    assert report["screenshot_hash_mismatches"] == []
    assert report["missing_ui_trees"] == []
    assert report["unpaired_capture_files"] == []
    assert report["coverage_arithmetic_ok"] is True


def test_audit_capture_bundle_fails_when_a_referenced_screenshot_changes(tmp_path: Path):
    evidence, coverage, screenshot = _write_bundle(tmp_path)
    screenshot.write_bytes(b"tampered")

    report = audit_capture_bundle(evidence, coverage)

    assert report["integrity_status"] == "FAIL"
    assert report["screenshot_hash_mismatches"] == ["screen-0001"]

