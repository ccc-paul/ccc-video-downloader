"""主窗口: 单页工具, 只有视频下载.

与 CCC Live Studio 主线不同, 这里**没有导航菜单、没有设置页、没有帮助页** ——
整个程序就一个功能, 多一层导航反而是负担。窗口直接以下载页作为中央控件。

底部状态栏只报两件与下载直接相关的事: ffmpeg 和 JS 运行时在不在。
这两个缺一个下载就会出问题 (不能合并音视频 / 403), 放在眼前比藏进帮助页管用。
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QLabel, QMainWindow, QStatusBar

from app import APP_NAME, __version__
from app.infra.ffmpeg import is_available as ffmpeg_available
from app.infra.i18n import t
from app.infra.jsruntime import is_available as js_runtime_available
from app.infra.logger import get_logger
from app.ui.pages.downloader_page import DownloaderPage

_STYLE_PATH = Path(__file__).parent / "resources" / "styles.qss"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._log = get_logger("ui")
        self.setWindowTitle(f"{APP_NAME}  v{__version__}")
        self.resize(1100, 720)
        self.setMinimumSize(QSize(900, 560))

        self._page = DownloaderPage()
        self.setCentralWidget(self._page)

        self._build_status_bar()
        self._apply_stylesheet()

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        bar.setFixedHeight(24)
        bar.addWidget(QLabel(self._dot(t("status.ffmpeg"), ffmpeg_available())))
        bar.addWidget(QLabel(self._dot(t("status.jsruntime"), js_runtime_available())))
        bar.addPermanentWidget(QLabel(f"v{__version__}"))
        self.setStatusBar(bar)

    @staticmethod
    def _dot(name: str, ok: bool) -> str:
        return f"{'●' if ok else '○'} {name}"

    def _apply_stylesheet(self) -> None:
        if not _STYLE_PATH.exists():
            self._log.warning("样式表缺失: {}", _STYLE_PATH)
            return
        qss = _STYLE_PATH.read_text(encoding="utf-8")
        # {RES} → resources 目录绝对路径 (正斜杠, QSS 的 url() 不吃反斜杠).
        # 相对 url() 按进程工作目录解析, 打包后必然找不到图, 所以在这里换掉.
        self.setStyleSheet(qss.replace("{RES}", _STYLE_PATH.parent.as_posix()))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API)
        """关窗前收尾: 取消在跑的下载并等线程退出."""
        try:
            self._page.shutdown()
        except Exception as e:  # noqa: BLE001 — 关窗路径不能因收尾失败而卡住
            self._log.warning("收尾失败: {}", e)
        super().closeEvent(event)
