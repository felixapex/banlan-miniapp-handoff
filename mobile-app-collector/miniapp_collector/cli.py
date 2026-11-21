from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

from collector_core.capture_audit import audit_capture_bundle
from collector_core.evidence import save_evidence
from collector_core.explorer import (
    DEFAULT_DENY_TERMS,
    SafeStateExplorer,
    build_interaction_coverage,
)

from .client import MiniappAdbClient, SHARE_LINK, classify_miniapp_link


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="miniapp-collector",
        description="WeChat mini-program collector for a dedicated Android test account",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="read-only ADB and WeChat checks")
    doctor.add_argument("--adb", default="adb")
    doctor.add_argument("--serial")

    capture = sub.add_parser("capture", help="capture an authorized WeChat mini-program")
    capture.add_argument("--adb", default="adb")
    capture.add_argument("--serial")
    capture.add_argument("--link", required=True)
    capture.add_argument("--app-id")
    capture.add_argument("--app-name")
    capture.add_argument("--dedicated-test-account", action="store_true")
    capture.add_argument("--allow-share-text-input", action="store_true")
    capture.add_argument("--account-pause-file")
    capture.add_argument("--max-screens", type=int, default=30)
    capture.add_argument("--max-depth", type=int, default=3)
    capture.add_argument("--max-actions-per-screen", type=int, default=8)
    capture.add_argument("--max-scrolls-per-screen", type=int, default=2)
    capture.add_argument("--progress-every", type=int, default=10)
    capture.add_argument("--deny-term", action="append", default=[])
    capture.add_argument("--out", required=True)

    verify = sub.add_parser("verify", help="verify a mini-program capture bundle")
    verify.add_argument("--evidence", required=True)
    verify.add_argument("--coverage", required=True)
    verify.add_argument("--out", required=True)
    return parser


def _target_identity(link: str, app_id: str | None) -> str:
    if app_id:
        if not re.fullmatch(r"wx[a-fA-F0-9]{16}", app_id):
            raise SystemExit("--app-id must be an 18-character WeChat mini-program AppID")
        return app_id
    return f"wechat-miniapp:{sha256(link.encode('utf-8')).hexdigest()[:16]}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify":
        report = audit_capture_bundle(args.evidence, args.coverage)
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["integrity_status"] == "PASS" else 2

    if args.command == "capture":
        if not args.dedicated_test_account:
            raise SystemExit("capture requires a dedicated test account: pass --dedicated-test-account")
        if args.account_pause_file and Path(args.account_pause_file).is_file():
            raise SystemExit(f"account automation is paused: {args.account_pause_file}")
        kind = classify_miniapp_link(args.link)
        if kind == "wechat_share_text" and not args.allow_share_text_input:
            raise SystemExit("#小程序 share text requires --allow-share-text-input")
        target_id = _target_identity(args.link, args.app_id)
    else:
        target_id = "wechat-miniapp:doctor"

    client = MiniappAdbClient(args.adb, target_id=target_id, serial=args.serial)
    serial = client.select()
    if args.command == "doctor":
        print(json.dumps({"status": "READY", "serial": serial, "wechat": "installed"}))
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    checkpoint_path = out / "checkpoint-evidence.json"

    def save_checkpoint(app) -> None:
        save_evidence(app, checkpoint_path)

    client.open_miniapp_link(
        args.link,
        allow_share_text_input=args.allow_share_text_input,
    )
    restore_callback = None
    if kind != "wechat_share_text":
        restore_callback = lambda: client.open_miniapp_link(args.link)
    explorer = SafeStateExplorer(
        client,
        deny_terms=DEFAULT_DENY_TERMS + tuple(args.deny_term),
        restore_callback=restore_callback,
        progress_callback=save_checkpoint,
        progress_every=args.progress_every,
    )
    name_match = SHARE_LINK.fullmatch(args.link)
    app_name = args.app_name or (name_match.group(1) if name_match else target_id)
    app = explorer.explore(
        app_id=target_id,
        app_name=app_name,
        platform="wechat-miniapp",
        app_version=None,
        capture_source="adb-wechat",
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
        deny_terms=DEFAULT_DENY_TERMS + tuple(args.deny_term),
    )
    coverage_path = out / "interaction-coverage.json"
    coverage_path.write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "CAPTURED",
        "platform": "wechat-miniapp",
        "serial": serial,
        "evidence": str(evidence_path),
        "coverage": str(coverage_path),
        "coverage_status": coverage["status"],
        "screens": len(app.screens),
    }, ensure_ascii=False, indent=2))
    return 0
