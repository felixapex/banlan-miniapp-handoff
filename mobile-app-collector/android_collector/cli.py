from __future__ import annotations

from collector_core.command import build_platform_parser, run_command

from .client import AndroidAppiumClient


def build_parser():
    return build_platform_parser(
        prog="android-collector",
        platform_label="Android",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_command(
        args,
        platform="android",
        client_class=AndroidAppiumClient,
    )
