"""主窗口: 单页工具, 只有视频下载.

与 CCC Live Studio 主线不同, 这里**没有导航菜单、没有设置页、没有帮助页** ——
整个程序就一个功能, 多一层导航反而是负担。窗口直接以下载页作为中央控件。

底部状态栏报三件与下载直接相关的事: yt-dlp 版本、ffmpeg、JS 运行时。
缺哪个下载都会出问题 (下不了 / 不能合并音视频 / 403), 放在眼前比藏进帮助页管用。

启动时会在后台让 yt-dlp 自更新一次 —— YouTube 每隔几周换播放器, 旧版立刻全线
403, 这是让用户不必等我们重打安装包就能跟上的唯一办法。更新失败一律不影响使用。
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QLabel, QMainWindow, QStatusBar

from app import APP_NAME, __version__
from app.infra import ytdlp_bin
from app.infra.ffmpeg import is_available as ffmpeg_available
from app.infra.i18n import t
from app.infra.jsruntime import is_available as js_runtime_available
from app.infra.logger import get_logger
from app.ui.pages.downloader_page import DownloaderPage

_STYLE_PATH = Path(__file__).parent / "resources" / "styles.qss"


class _UpdateWorker(QObject):
    """后台跑 yt-dlp 自更新. done(是否更新了, 说明文字)."""

    done = pyqtSignal(bool, str)

    def run(self) -> None:
        try:
            changed, message = ytdlp_bin.self_update()
        except Exception as e:  # noqa: BLE001 — 更新失败绝不能影响主功能
            changed, message = False, f"更新异常 (不影响使用): {e}"
        self.done.emit(changed, message)


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
        self._start_ytdlp_update()

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        bar.setFixedHeight(24)
        self._ytdlp_label = QLabel(self._ytdlp_status_text())
        bar.addWidget(self._ytdlp_label)
        bar.addWidget(QLabel(self._dot(t("status.ffmpeg"), ffmpeg_available())))
        bar.addWidget(QLabel(self._dot(t("status.jsruntime"), js_runtime_available())))
        bar.addPermanentWidget(QLabel(f"v{__version__}"))
        self.setStatusBar(bar)

    def _ytdlp_status_text(self) -> str:
        ok, detail = ytdlp_bin.probe()
        return self._dot(f"yt-dlp {detail}" if ok else "yt-dlp", ok)

    # ---------- yt-dlp 自更新 ----------

    def _start_ytdlp_update(self) -> None:
        """启动时在后台更新一次. 绝不阻塞 UI, 失败静默 (只进日志)."""
        self._update_thread = QThread(self)
        self._update_worker = _UpdateWorker()
        self._update_worker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.done.connect(self._on_update_done)
        self._update_worker.done.connect(self._update_thread.quit)
        self._update_thread.finished.connect(self._update_thread.deleteLater)
        self._update_thread.finished.connect(self._update_worker.deleteLater)
        self._update_thread.start()

    def _on_update_done(self, changed: bool, message: str) -> None:
        self._log.info("{}", message)
        if changed:
            # 版本变了, 状态栏要跟上 (下次下载就用新版了)
            self._ytdlp_label.setText(self._ytdlp_status_text())

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
        # 更新线程可能还在跑 (自更新要连网, 最长 120s). 等一小会儿就够了 ——
        # 它只写 APPDATA 下那个副本, 中途被打断顶多是这次没更新成。
        thread = getattr(self, "_update_thread", None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(3000)
        super().closeEvent(event)
