from __future__ import annotations

from collector_core.command import build_platform_parser, run_command

from .client import IOSAppiumClient


def build_parser():
    return build_platform_parser(
        prog="ios-collector",
        platform_label="iOS",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_command(
        args,
        platform="ios",
        client_class=IOSAppiumClient,
    )
