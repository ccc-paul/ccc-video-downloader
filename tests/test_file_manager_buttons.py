"""两个"去文件管理器"的入口 (2026-08-24 反馈).

用户点「浏览...」想去 Finder 看下好的文件, 结果弹出的是目录选择框 (文件全灰) ——
那是它该干的事, 但缺一个"直接打开这个文件夹"的入口。同时发现队列行的 📂 一直只是
打开父目录, 而 README 承诺的是**选中**那个文件, reveal_in_file_manager 写好了却没被调用。
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.core.ytdlp_wrapper import DownloadOptions
from app.infra.i18n import init_i18n, t
from app.services.download_service import DownloadJob
from app.ui.pages import downloader_page as page_mod
from app.ui.pages.downloader_page import DownloaderPage, _JobRowWidget


@pytest.fixture(scope="module")
def _qapp():
    init_i18n()
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def page(_qapp):
    return DownloaderPage()


class TestOpenSaveDir:
    def test_点了就打开当前保存目录(self, page, tmp_path, monkeypatch):
        opened: list[Path] = []
        monkeypatch.setattr(page_mod, "open_in_file_manager", lambda p: opened.append(Path(p)))

        page._output_dir.setText(str(tmp_path))
        page._open_dir_btn.click()

        assert opened == [tmp_path], "应该把当前保存目录交给文件管理器"

    def test_目录不存在时给提示而不是静悄悄(self, page, tmp_path, monkeypatch):
        """按钮点了什么都不发生, 用户只会以为程序坏了。"""
        opened = []
        warned = []
        monkeypatch.setattr(page_mod, "open_in_file_manager", lambda p: opened.append(p))
        monkeypatch.setattr(QMessageBox, "warning",
                            staticmethod(lambda *a, **kw: warned.append(a[2])))

        page._output_dir.setText(str(tmp_path / "早就删了"))
        page._open_dir_btn.click()

        assert opened == []
        assert warned and "早就删了" in warned[0]

    def test_没填目录时提示先选位置(self, page, monkeypatch):
        opened = []
        warned = []
        monkeypatch.setattr(page_mod, "open_in_file_manager", lambda p: opened.append(p))
        monkeypatch.setattr(QMessageBox, "warning",
                            staticmethod(lambda *a, **kw: warned.append(a[2])))

        page._output_dir.setText("   ")
        page._open_dir_btn.click()

        assert opened == []
        assert warned == [t("downloader.error.no_dir")]

    def test_浏览按钮仍然是选目录(self, page, tmp_path, monkeypatch):
        """新按钮是**加**的, 不能把选保存位置的能力换掉。"""
        monkeypatch.setattr(page_mod.QFileDialog, "getExistingDirectory",
                            staticmethod(lambda *a, **kw: str(tmp_path / "新位置")))
        page._on_browse_dir()
        assert page._output_dir.text() == str(tmp_path / "新位置")


class TestRowOpen:
    def _row(self, tmp_path) -> _JobRowWidget:
        job = DownloadJob("https://www.youtube.com/watch?v=x",
                          DownloadOptions("mp4", "1080", tmp_path))
        row = _JobRowWidget(job)
        return row

    def test_点打开按钮是选中文件而不是只打开文件夹(self, _qapp, tmp_path, monkeypatch):
        revealed: list[Path] = []
        monkeypatch.setattr(page_mod, "reveal_in_file_manager",
                            lambda p: revealed.append(Path(p)))

        row = self._row(tmp_path)
        video = tmp_path / "某个视频.mp4"
        video.write_bytes(b"x")
        row._job.output_path = video
        row._open_btn.click()

        assert revealed == [video], "要把文件本身交出去 (mac open -R / Windows /select)"

    def test_还没有输出文件时点了不炸(self, _qapp, tmp_path, monkeypatch):
        revealed = []
        monkeypatch.setattr(page_mod, "reveal_in_file_manager", lambda p: revealed.append(p))
        row = self._row(tmp_path)
        row._open_btn.click()          # output_path 还是 None
        assert revealed == []
