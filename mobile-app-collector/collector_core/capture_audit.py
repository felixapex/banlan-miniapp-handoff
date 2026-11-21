from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from .evidence import load_evidence, resolve_evidence_asset, sha256_file


def _capture_pair_key(path: Path) -> str:
    stem = path.stem
    return stem.removesuffix("__default")


def audit_capture_bundle(
    evidence_path: str | Path,
    coverage_path: str | Path,
) -> dict[str, object]:
    """Verify capture graph, referenced assets, hashes, capture pairs, and coverage arithmetic.

    Integrity and interaction coverage are deliberately separate. A technically sound bundle can
    still have INCOMPLETE button coverage, and this report must preserve that distinction.
    """
    evidence_file = Path(evidence_path).resolve()
    coverage_file = Path(coverage_path).resolve()
    app = load_evidence(evidence_file)

    missing_screenshots: list[str] = []
    screenshot_hash_mismatches: list[str] = []
    missing_ui_trees: list[str] = []
    for screen in app.screens:
        screenshot = resolve_evidence_asset(evidence_file, screen.screenshot_path)
        if not screenshot.is_file():
            missing_screenshots.append(screen.screen_id)
        elif sha256_file(screenshot) != screen.screenshot_sha256:
            screenshot_hash_mismatches.append(screen.screen_id)
        if not screen.ui_tree_path:
            missing_ui_trees.append(screen.screen_id)
        else:
            ui_tree = resolve_evidence_asset(evidence_file, screen.ui_tree_path)
            if not ui_tree.is_file():
                missing_ui_trees.append(screen.screen_id)

    capture_dir = evidence_file.parent / "capture"
    png_files = sorted(capture_dir.glob("*.png")) if capture_dir.is_dir() else []
    xml_files = sorted(capture_dir.glob("*.xml")) if capture_dir.is_dir() else []
    png_keys = {_capture_pair_key(path) for path in png_files}
    xml_keys = {_capture_pair_key(path) for path in xml_files}
    unpaired_capture_files = sorted(png_keys ^ xml_keys)
    empty_capture_files = sorted(
        str(path)
        for path in [*png_files, *xml_files]
        if path.stat().st_size == 0
    )

    coverage = json.loads(coverage_file.read_text(encoding="utf-8"))
    controls = coverage.get("controls", [])
    status_counts = Counter(item.get("status") for item in controls)
    total_controls = coverage.get("total_controls")
    verified_controls = coverage.get("verified_controls")
    blocked_controls = coverage.get("blocked_controls")
    unverified_controls = coverage.get("unverified_controls")
    coverage_arithmetic_ok = (
        all(isinstance(value, int) for value in (
            total_controls,
            verified_controls,
            blocked_controls,
            unverified_controls,
        ))
        and total_controls == len(controls)
        and total_controls == verified_controls + blocked_controls + unverified_controls
        and verified_controls == status_counts.get("VERIFIED", 0)
        and blocked_controls == sum(
            count for status, count in status_counts.items()
            if isinstance(status, str) and status.startswith("BLOCKED_")
        )
        and unverified_controls == status_counts.get("UNVERIFIED", 0)
    )

    defects = [
        *missing_screenshots,
        *screenshot_hash_mismatches,
        *missing_ui_trees,
        *unpaired_capture_files,
        *empty_capture_files,
    ]
    if not coverage_arithmetic_ok:
        defects.append("coverage_arithmetic")

    return {
        "integrity_status": "FAIL" if defects else "PASS",
        "coverage_status": coverage.get("status", "UNKNOWN"),
        "app_id": app.app_id,
        "platform": app.platform,
        "screens": len(app.screens),
        "flows": len(app.flows),
        "flow_steps": sum(len(flow.steps) for flow in app.flows),
        "capture_png": len(png_files),
        "capture_xml": len(xml_files),
        "missing_screenshots": missing_screenshots,
        "screenshot_hash_mismatches": screenshot_hash_mismatches,
        "missing_ui_trees": missing_ui_trees,
        "unpaired_capture_files": unpaired_capture_files,
        "empty_capture_files": empty_capture_files,
        "coverage_arithmetic_ok": coverage_arithmetic_ok,
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "evidence_sha256": sha256_file(evidence_file),
        "coverage_sha256": sha256_file(coverage_file),
    }
