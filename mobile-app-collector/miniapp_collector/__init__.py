"""WeChat mini-program collector entry package."""

from .client import MiniappAdbClient, classify_miniapp_link

__all__ = ["MiniappAdbClient", "classify_miniapp_link"]
