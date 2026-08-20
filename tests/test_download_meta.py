"""下载队列新增字段的纯逻辑单测: 实际画质提取 + 文件大小格式化."""
from __future__ import annotations

from app.services.download_service import _extract_quality
from app.ui.pages.downloader_page import _human_size


class TestExtractQuality:
    def test_mp4_merged_uses_video_stream_height(self):
        info = {"requested_formats": [{"height": 1080}, {"vcodec": "none", "acodec": "mp4a"}]}
        assert _extract_quality(info, "mp4") == "1080p"

    def test_mp4_flat_height(self):
        assert _extract_quality({"height": 720}, "mp4") == "720p"

    def test_mp4_resolution_fallback(self):
        assert _extract_quality({"resolution": "1280x720"}, "mp4") == "1280x720"

    def test_mp4_audio_only_resolution_ignored(self):
        assert _extract_quality({"resolution": "audio only"}, "mp4") == ""

    def test_mp3_uses_bitrate(self):
        assert _extract_quality({"abr": 192.0}, "mp3") == "192 kbps"

    def test_missing_is_empty(self):
        assert _extract_quality({}, "mp4") == ""


class TestHumanSize:
    def test_bytes(self):
        assert _human_size(512) == "512 B"

    def test_kb(self):
        assert _human_size(2048) == "2.0 KB"

    def test_mb(self):
        assert _human_size(int(45.2 * 1024 * 1024)) == "45.2 MB"

    def test_gb(self):
        assert _human_size(3 * 1024 ** 3) == "3.0 GB"
