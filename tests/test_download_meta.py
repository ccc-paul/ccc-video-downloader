"""下载队列的文件大小格式化.

实际画质的提取已随 2026-08-21 的 CLI 化改造搬进 ytdlp_wrapper.parse_file,
对应用例见 test_ytdlp_wrapper.py::TestParseFile。
"""
from __future__ import annotations

from app.ui.pages.downloader_page import _human_size


class TestHumanSize:
    def test_bytes(self):
        assert _human_size(512) == "512 B"

    def test_kb(self):
        assert _human_size(2048) == "2.0 KB"

    def test_mb(self):
        assert _human_size(int(45.2 * 1024 * 1024)) == "45.2 MB"

    def test_gb(self):
        assert _human_size(3 * 1024 ** 3) == "3.0 GB"
