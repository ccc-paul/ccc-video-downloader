"""视频下载器 - 应用入口."""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from app import APP_NAME, __version__
from app.infra.ffmpeg import find_ffmpeg
from app.infra.i18n import init_i18n
from app.infra.jsruntime import find_js_runtime
from app.infra.local_db import init_db
from app.infra.logger import get_logger, setup_logging
from app.ui.main_window import MainWindow


def _log_dependencies(log) -> None:
    """把两个外部可执行文件的解析结果记进日志.

    同事报"下载失败"时, 让他把日志发来 —— 头两行就能看出是不是缺 ffmpeg/deno,
    省掉一轮来回。打包后也能借此确认 vendor 真的进了 _MEIPASS。
    """
    ffmpeg = find_ffmpeg()
    log.info("ffmpeg: {}", ffmpeg or "未找到 (无法合并音视频)")

    runtime = find_js_runtime()
    log.info(
        "JS 运行时: {}",
        f"{runtime[0]} @ {runtime[1]}" if runtime else "未找到 (下载很可能 403)",
    )


def main() -> int:
    setup_logging()
    log = get_logger("system")
    log.info("{} v{} 启动 (frozen={})", APP_NAME, __version__, hasattr(sys, "_MEIPASS"))

    lang = init_i18n()
    log.info("界面语言: {}", lang)
    _log_dependencies(log)

    init_db()

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName(APP_NAME)
    qt_app.setApplicationVersion(__version__)

    window = MainWindow()
    window.show()

    exit_code = qt_app.exec()
    log.info("应用退出 code={}", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
