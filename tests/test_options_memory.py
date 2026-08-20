"""选项记忆: 本工具没有设置页, 全靠"记住上次用的"来免去每次重填.

所以这条路径坏了 = 用户每次打开都要重选目录/格式/画质, 体感很差, 值得盯住。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from app.infra import config


@pytest.fixture(scope="module")
def _qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """把 config 指到临时目录, 别动开发机上真实的配置."""
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "APPDATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    return cfg_path


@pytest.fixture
def page(_qapp, isolated_config):
    from app.ui.pages.downloader_page import DownloaderPage

    return DownloaderPage()


class TestDefaults:
    def test_first_run_uses_videos_folder(self, page):
        """首次运行没有配置, 应落在系统「视频」文件夹, 而不是空白或某个教会目录."""
        assert page._output_dir.text() == str(config.default_download_dir())

    def test_default_download_dir_exists_or_home(self):
        d = config.default_download_dir()
        assert d.is_dir(), f"{d} 不存在, 用户一点浏览就懵了"

    def test_macos_uses_movies_not_videos(self, monkeypatch):
        """macOS 的视频目录叫 Movies —— 写死 Videos 的话 Mac 上会一路回落到主目录,
        下载全散在 ~ 底下 (2026-08-20 修)."""
        monkeypatch.setattr(config.sys, "platform", "darwin")
        monkeypatch.setattr(config.Path, "home", staticmethod(lambda: Path("/Users/x")))
        monkeypatch.setattr(Path, "is_dir", lambda self: True)

        assert config.default_download_dir() == Path("/Users/x/Movies")

    def test_windows_uses_videos(self, monkeypatch):
        monkeypatch.setattr(config.sys, "platform", "win32")
        monkeypatch.setattr(config.Path, "home", staticmethod(lambda: Path("/home/x")))
        monkeypatch.setattr(Path, "is_dir", lambda self: True)

        assert config.default_download_dir() == Path("/home/x/Videos")

    def test_defaults_mp4_1080(self, page):
        assert page._radio_mp4.isChecked()
        assert page._video_quality.currentData() == "1080"


class TestRemember:
    def test_writes_config(self, page, isolated_config, tmp_path):
        target = tmp_path / "我的下载"
        target.mkdir()
        page._output_dir.setText(str(target))
        page._radio_mp3.setChecked(True)
        page._remember_options()

        saved = json.loads(isolated_config.read_text(encoding="utf-8"))["download"]
        assert saved["output_dir"] == str(target)
        assert saved["format_kind"] == "mp3"

    def test_restored_on_next_launch(self, page, isolated_config, tmp_path, _qapp):
        from app.ui.pages.downloader_page import DownloaderPage

        target = tmp_path / "上次选的目录"
        target.mkdir()
        page._output_dir.setText(str(target))
        page._radio_mp3.setChecked(True)
        page._audio_quality.setCurrentIndex(page._audio_quality.findData("320"))
        page._remember_options()

        fresh = DownloaderPage()  # 模拟重新打开程序

        assert fresh._output_dir.text() == str(target)
        assert fresh._radio_mp3.isChecked()
        assert fresh._audio_quality.currentData() == "320"


class TestRobustness:
    def test_corrupt_config_falls_back(self, isolated_config, _qapp):
        """配置文件损坏也要能打开 —— 这是给非技术同事用的, 不能开不了."""
        isolated_config.write_text("{ 这不是合法 JSON", encoding="utf-8")
        from app.ui.pages.downloader_page import DownloaderPage

        page = DownloaderPage()
        assert page._output_dir.text() == str(config.default_download_dir())

    def test_unknown_quality_falls_back(self, isolated_config, _qapp):
        """配置里存了一个已经不存在的画质选项, 不能让下拉框空着."""
        isolated_config.write_text(
            json.dumps({"download": {"video_quality": "8640"}}), encoding="utf-8"
        )
        from app.ui.pages.downloader_page import DownloaderPage

        page = DownloaderPage()
        assert page._video_quality.currentData() == "1080"

    def test_missing_dir_still_shown(self, isolated_config, _qapp, tmp_path):
        """上次的目录被删了: 仍显示出来让用户看见并自行改, 不要静默换成别处."""
        gone = tmp_path / "已经删掉的目录"
        isolated_config.write_text(
            json.dumps({"download": {"output_dir": str(gone)}}), encoding="utf-8"
        )
        from app.ui.pages.downloader_page import DownloaderPage

        page = DownloaderPage()
        assert page._output_dir.text() == str(gone)

    def test_save_failure_does_not_raise(self, isolated_config, monkeypatch):
        """配置写不进去 (只读盘/权限) 也不能打断下载."""
        def boom(_cfg):
            raise OSError("拒绝访问")

        monkeypatch.setattr(config, "save_config", boom)
        config.remember_download_options(
            output_dir="x", format_kind="mp4", video_quality="1080", audio_quality="192"
        )


class TestDataDirIsolatedFromMainApp:
    def test_folder_name_not_shared_with_live_studio(self):
        """与主线 CCCLiveStudio 分开存, 两个程序可以并存互不干扰."""
        from app import APP_FOLDER

        assert APP_FOLDER == "VideoDownloader"
        assert "CCCLiveStudio" not in str(config.APPDATA_DIR)
