"""冒烟测试: 启动应用 -> 1.5s 后自动退出. 验证 Sprint 0 骨架可运行."""
from __future__ import annotations

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from app import APP_NAME, __version__
from app.infra.i18n import init_i18n
from app.infra.local_db import init_db
from app.infra.logger import get_logger, setup_logging
from app.ui.main_window import MainWindow


def main() -> int:
    setup_logging()
    log = get_logger("smoke")
    log.info("{} v{} 冒烟测试", APP_NAME, __version__)

    init_i18n()
    init_db()

    qt_app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    QTimer.singleShot(1500, qt_app.quit)
    exit_code = qt_app.exec()
    log.info("冒烟测试结束 code={}", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
