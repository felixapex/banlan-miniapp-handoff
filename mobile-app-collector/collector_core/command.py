from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Type

from .capture_audit import audit_capture_bundle
from .evidence import load_evidence, save_evidence
from .explorer import (
    DEFAULT_DENY_TERMS,
    SafeStateExplorer,
    build_interaction_coverage,
    build_resume_records,
)
from .webdriver import BaseAppiumClient


def _json_object(raw: str, option: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{option} must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{option} must be a JSON object")
    return value


def build_platform_parser(*, prog: str, platform_label: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=f"{platform_label} application screenshot and UI evidence collector",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", help=f"capture an authorized {platform_label} app")
    capture.add_argument("--appium-url", required=True)
    capture.add_argument("--appium-options-json", required=True)
    capture.add_argument("--app-id", required=True)
    capture.add_argument("--app-name", required=True)
    capture.add_argument("--app-version")
    capture.add_argument("--resume-evidence")
    capture.add_argument("--start-url")
    capture.add_argument("--start-url-settle-seconds", type=float, default=3.0)
    capture.add_argument("--max-screens", type=int, default=30)
    capture.add_argument("--max-depth", type=int, default=3)
    capture.add_argument("--max-actions-per-screen", type=int, default=6)
    capture.add_argument("--max-scrolls-per-screen", type=int, default=1)
    capture.add_argument("--progress-every", type=int, default=10)
    capture.add_argument("--deny-term", action="append", default=[])
    capture.add_argument("--out", required=True)

    verify = sub.add_parser("verify", help="verify a completed or interrupted capture bundle")
    verify.add_argument("--evidence", required=True)
    verify.add_argument("--coverage", required=True)
    verify.add_argument("--out", required=True)
    return parser


def run_command(
    args: argparse.Namespace,
    *,
    platform: str,
    client_class: Type[BaseAppiumClient],
) -> int:
    if args.command == "verify":
        report = audit_capture_bundle(args.evidence, args.coverage)
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["integrity_status"] == "PASS" else 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    checkpoint_path = out / "checkpoint-evidence.json"

    def save_checkpoint(app) -> None:
        save_evidence(app, checkpoint_path)

    previous_verified_controls: list[dict[str, object]] = []
    terminal_skip_controls: list[dict[str, object]] = []
    if args.resume_evidence:
        previous_app = load_evidence(args.resume_evidence)
        if previous_app.app_id != args.app_id:
            raise SystemExit(
                f"--resume-evidence app_id mismatch: expected {args.app_id}, got {previous_app.app_id}"
            )
        if previous_app.platform.casefold() != platform.casefold():
            raise SystemExit(
                f"--resume-evidence platform mismatch: expected {platform}, got {previous_app.platform}"
            )
        previous_verified_controls = build_resume_records(previous_app)
        terminal_skip_controls = [
            record for record in previous_verified_controls
            if record["terminal"]
        ]

    client = client_class(args.appium_url)
    options = _json_object(args.appium_options_json, "--appium-options-json")
    client.start_session(options)
    try:
        restore_callback = None
        if args.start_url:
            client.open_deep_link(args.start_url, args.app_id)
            if args.start_url_settle_seconds > 0:
                time.sleep(args.start_url_settle_seconds)

            def restore_callback() -> None:
                client.open_deep_link(args.start_url, args.app_id)
                if args.start_url_settle_seconds > 0:
                    time.sleep(args.start_url_settle_seconds)

        deny_terms = DEFAULT_DENY_TERMS + tuple(args.deny_term)
        explorer_options = {
            "deny_terms": deny_terms,
            "restore_callback": restore_callback,
            "progress_callback": save_checkpoint,
            "progress_every": args.progress_every,
        }
        if args.resume_evidence:
            explorer_options["skip_resume_records"] = terminal_skip_controls
        explorer = SafeStateExplorer(client, **explorer_options)
        app = explorer.explore(
            app_id=args.app_id,
            app_name=args.app_name,
            platform=platform,
            app_version=args.app_version,
            out_dir=out / "capture",
            max_screens=args.max_screens,
            max_depth=args.max_depth,
            max_actions_per_screen=args.max_actions_per_screen,
            max_scrolls_per_screen=args.max_scrolls_per_screen,
        )
        evidence_path = out / "evidence.json"
        save_evidence(app, evidence_path)
        coverage = build_interaction_coverage(
            app,
            deny_terms=deny_terms,
            previously_verified_controls=previous_verified_controls,
        )
        coverage_path = out / "interaction-coverage.json"
        coverage_path.write_text(
            json.dumps(coverage, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({
            "status": "CAPTURED",
            "platform": platform,
            "coverage_status": coverage["status"],
            "evidence": str(evidence_path),
            "coverage": str(coverage_path),
            "checkpoint": str(checkpoint_path),
            "screens": len(app.screens),
            "resumed_verified_controls": len(previous_verified_controls),
            "skipped_terminal_controls": len(terminal_skip_controls),
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        client.stop_session()
