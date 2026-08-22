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
from app.infra import probe, ytdlp_bin
from app.infra.ffmpeg import is_available as ffmpeg_available
from app.infra.i18n import t
from app.infra.jsruntime import is_available as js_runtime_available
from app.infra.logger import get_logger
from app.ui.pages.downloader_page import DownloaderPage

_STYLE_PATH = Path(__file__).parent / "resources" / "styles.qss"


class _UpdateWorker(QObject):
    """后台探版本 + 跑 yt-dlp 自更新.

    探版本也放这儿, 是因为 mac 上跑一次 `--version` 要 8~12s (官方包是 PyInstaller
    onefile, 每次执行都重新解包) —— 摆在主线程上, 窗口要么迟迟不出来, 要么出来就是
    一片空白点不动。先 probed(...) 让状态栏落地, 再慢慢更新。

    probed(能否执行, 版本串或失败原因) / done(是否更新了, 说明文字)
    """

    probed = pyqtSignal(bool, str)
    done = pyqtSignal(bool, str)

    def run(self) -> None:
        try:
            ok, detail = ytdlp_bin.probe()
        except Exception as e:  # noqa: BLE001 — 探测失败也只是显示不出版本
            ok, detail = False, f"探测异常: {e}"
        self.probed.emit(ok, detail)

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
        # 真实状态由后台线程探完再填 (见 _UpdateWorker), 这里先给个"检测中"
        self._ytdlp_label = QLabel(f"⋯ {t('status.ytdlp.checking')}")
        bar.addWidget(self._ytdlp_label)
        bar.addWidget(QLabel(self._dot(t("status.ffmpeg"), ffmpeg_available())))
        bar.addWidget(QLabel(self._dot(t("status.jsruntime"), js_runtime_available())))
        bar.addPermanentWidget(QLabel(f"v{__version__}"))
        self.setStatusBar(bar)

    def _on_ytdlp_probed(self, ok: bool, detail: str) -> None:
        self._log.info("yt-dlp: {}", detail if ok else f"不可用 —— {detail}")
        self._ytdlp_label.setText(self._dot(f"yt-dlp {detail}" if ok else "yt-dlp", ok))

    # ---------- yt-dlp 自更新 ----------

    def _start_ytdlp_update(self) -> None:
        """启动时在后台更新一次. 绝不阻塞 UI, 失败静默 (只进日志)."""
        self._update_thread = QThread(self)
        self._update_worker = _UpdateWorker()
        self._update_worker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.probed.connect(self._on_ytdlp_probed)
        self._update_worker.done.connect(self._on_update_done)
        self._update_worker.done.connect(self._update_thread.quit)
        # 清引用要接在 deleteLater 前面 —— 两条都是排队送回主线程, 按连接顺序执行
        self._update_thread.finished.connect(self._forget_update_thread)
        self._update_thread.finished.connect(self._update_thread.deleteLater)
        self._update_thread.finished.connect(self._update_worker.deleteLater)
        self._update_thread.start()

    def _forget_update_thread(self) -> None:
        """线程跑完就把引用清掉 —— 下面 deleteLater 一执行, C++ 对象就没了。

        不清的后果是关窗必崩: closeEvent 里 `thread.isRunning()` 访问的是已析构的
        QThread, 抛 `RuntimeError: wrapped C/C++ object of type QThread has been
        deleted`; **PyQt6 对虚函数里未捕获的 Python 异常直接 abort**
        (Windows 退出码 0xC0000409), super().closeEvent() 连跑都跑不到。
        触发条件很日常: 开着程序超过自更新那几秒再关窗就中。
        """
        self._update_thread = None
        self._update_worker = None

    def _on_update_done(self, changed: bool, message: str) -> None:
        self._log.info("{}", message)
        if changed:
            # 版本变了, 状态栏要跟上 (下次下载就用新版了)。self_update 已经把新版本
            # 写进 probe 缓存, 这里读的是缓存, 不会再卡一次
            self._on_ytdlp_probed(*ytdlp_bin.probe())

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
        # 更新线程可能还在跑 (探版本 + 自更新, 最长 120s)。**光 quit()+wait() 不够**:
        # 线程正阻塞在子进程上, quit 只结束事件循环, wait 必然超时, 然后 QThread 带着
        # 未结束的线程被销毁 —— 进程直接 abort ("QThread: Destroyed while thread is
        # still running")。mac 上一次 --version 就 8~12s, 用户点关闭时它多半还在跑,
        # 所以必须先把子进程掐掉, 让 run() 返回。
        # 中途被打断顶多是这次没更新成 —— 它只写 APPDATA 下那个副本。
        try:
            probe.kill_running()
        except Exception as e:  # noqa: BLE001 — 关窗路径不能因收尾失败而卡住
            self._log.warning("停止更新子进程失败: {}", e)
        # isRunning() 也要护住: 正常情况下 _forget_update_thread 已经把引用清成
        # None, 但 deleteLater 是异步的, 关窗路径上任何一个异常都会让 PyQt6 abort,
        # 不值得赌顺序。
        thread = getattr(self, "_update_thread", None)
        try:
            running = thread is not None and thread.isRunning()
        except RuntimeError:  # C++ 对象已析构
            running = False
        if running:
            thread.quit()
            if not thread.wait(3000):
                self._log.warning("更新线程未在 3s 内退出")
        super().closeEvent(event)
