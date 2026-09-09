"""Optional media source adapters."""

from bili_tracker.adapters.sources.bilibili import BilibiliClient, BilibiliSource
from bili_tracker.adapters.sources.local_file import LocalFileSource
from bili_tracker.adapters.sources.ytdlp import YtDlpSource

__all__ = ["BilibiliClient", "BilibiliSource", "LocalFileSource", "YtDlpSource"]
