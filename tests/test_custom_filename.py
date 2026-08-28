"""界面上自定义输出文件名 (2026-08-27 反馈: 默认名字"长得惊人").

默认模板是 "%(title)s - %(uploader)s.%(ext)s", YouTube 标题动辄上百字符。
允许自己起名, 但用户输入的东西不能直接塞进 yt-dlp 的 -o。
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.core import ytdlp_wrapper as yw
from app.core.ytdlp_wrapper import (
    DEFAULT_FILENAME_TEMPLATE,
    MAX_FILENAME_STEM,
    filename_template_for,
    sanitize_stem,
    unique_stem,
)
from app.infra.i18n import init_i18n
from app.ui.pages import downloader_page as page_mod
from app.ui.pages.downloader_page import DownloaderPage


class TestSanitizeStem:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("我的视频", "我的视频"),
            ("a/b\\c:d*e?f\"g<h>i|j", "abcdefghij"),   # 路径分隔符和非法字符
            ("片子.mp4", "片子"),                        # 顺手打的扩展名
            ("片子.MP3", "片子"),
            ("  空格  ", "空格"),
            ("尾点...", "尾点"),                         # Windows 会悄悄吃掉结尾的点
            ("讲道 / 测试", "讲道 测试"),                 # 去掉 "/" 后留下的双空格要收掉
            ("", ""),
            ("///", ""),                                 # 洗完什么都不剩
        ],
    )
    def test_洗名字(self, raw, expected):
        assert sanitize_stem(raw) == expected

    @pytest.mark.parametrize("name", ["CON", "nul", "COM1", "LPT9"])
    def test_windows_保留名要改掉(self, name):
        """这些名字建出来的文件在 Windows 上打不开。"""
        assert sanitize_stem(name) == name + "_"

    def test_超长截断(self):
        assert len(sanitize_stem("字" * 500)) == MAX_FILENAME_STEM

    def test_不许穿越目录(self):
        """"../../etc/passwd" 洗完不能再含分隔符, 否则会写到别的目录去。"""
        stem = sanitize_stem("../../etc/passwd")
        assert "/" not in stem and "\\" not in stem


class TestTemplate:
    def test_空名字回落默认模板(self):
        assert filename_template_for("") == DEFAULT_FILENAME_TEMPLATE

    def test_普通名字(self):
        assert filename_template_for("讲道") == "讲道.%(ext)s"

    def test_百分号要转义(self):
        """yt-dlp 的输出模板里 % 有特殊含义, 不转义会被当成字段开头。"""
        assert filename_template_for("50%off") == "50%%off.%(ext)s"

    def test_模板真的进了命令行(self, tmp_path):
        opts = yw.DownloadOptions("mp4", "720", tmp_path,
                                  filename_template=filename_template_for("讲道"))
        args = yw.build_args(opts, "URL")
        assert str(tmp_path / "讲道.%(ext)s") in args


class TestUniqueStem:
    def test_没撞名就原样返回(self, tmp_path):
        assert unique_stem(tmp_path, "讲道", "mp4") == "讲道"

    def test_撞名补编号(self, tmp_path):
        (tmp_path / "讲道.mp4").write_bytes(b"x")
        assert unique_stem(tmp_path, "讲道", "mp4") == "讲道 (2)"
        (tmp_path / "讲道 (2).mp4").write_bytes(b"x")
        assert unique_stem(tmp_path, "讲道", "mp4") == "讲道 (3)"

    def test_不同扩展名互不影响(self, tmp_path):
        """同名的 mp3 不该让 mp4 改名。"""
        (tmp_path / "讲道.mp3").write_bytes(b"x")
        assert unique_stem(tmp_path, "讲道", "mp4") == "讲道"

    def test_空名字不动(self, tmp_path):
        assert unique_stem(tmp_path, "", "mp4") == ""


@pytest.fixture(scope="module")
def _qapp():
    init_i18n()
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def page(_qapp, tmp_path, monkeypatch):
    p = DownloaderPage()
    monkeypatch.setattr(page_mod, "ffmpeg_available", lambda: True)
    p._output_dir.setText(str(tmp_path))
    p._url_input.setText("https://www.youtube.com/watch?v=abc")
    return p


def _added(page) -> yw.DownloadOptions:
    """点一次「加入下载队列」, 把交给 service 的 options 抓出来."""
    captured = {}
    page._service.add_job = lambda url, options: captured.update(url=url, options=options)
    page._on_add()
    return captured.get("options")


class TestPage:
    def test_填了就用自定义名(self, page):
        page._filename_input.setText("讲道 20260827")
        assert _added(page).filename_template == "讲道 20260827.%(ext)s"

    def test_留空还是默认模板(self, page):
        assert _added(page).filename_template == DEFAULT_FILENAME_TEMPLATE

    def test_入队后清空(self, page):
        """文件名是一次性的, 不该被下一条链接继承。"""
        page._filename_input.setText("讲道")
        _added(page)
        assert page._filename_input.text() == ""

    def test_名字全是非法字符时报错而不是默默用默认名(self, page, monkeypatch):
        warned = []
        monkeypatch.setattr(QMessageBox, "warning",
                            staticmethod(lambda *a, **kw: warned.append(a[2])))
        page._filename_input.setText("//:*?")
        assert _added(page) is None, "不该入队"
        assert warned and "//:*?" in warned[0]

    def test_撞名自动补编号(self, page, tmp_path):
        (tmp_path / "讲道.mp4").write_bytes(b"x")
        page._filename_input.setText("讲道")
        assert _added(page).filename_template == "讲道 (2).%(ext)s"
