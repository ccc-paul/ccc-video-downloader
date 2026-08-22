"""冒烟测试: 起窗口 -> 关窗 -> 退出. 顺带守住两条关窗崩溃.

**关窗有两条路, 坑不一样, 必须各走一遍** —— 两条都真崩过:

A. 更新线程**还在跑**时关窗
   线程正阻塞在 yt-dlp 子进程上, quit() 只结束事件循环, wait() 必然超时,
   然后 QThread 带着活线程被销毁 => "QThread: Destroyed while thread is still
   running" 直接 abort。修法是先 probe.kill_running() 掐掉子进程。

B. 更新线程**跑完之后**关窗
   线程 finished 时 QThread 已被 deleteLater, closeEvent 再问 isRunning() 就是
   访问已析构的 C++ 对象, 抛 RuntimeError —— PyQt6 对虚函数里未捕获的异常
   直接 abort (Windows 退出码 0xC0000409)。

这个文件早先只关 A (起来 1.5s 就关), B 那条一直没人走 —— 于是 B 崩了很久都没
发现, 而 B 才是用户的日常: 开着程序超过自更新那几秒再关就中。
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from app import APP_NAME, __version__
from app.infra.i18n import init_i18n
from app.infra.local_db import init_db
from app.infra.logger import get_logger, setup_logging
from app.ui.main_window import MainWindow

# 等自更新跑完的兜底上限: 正常几秒就好, 网络慢/被公司网络挡住时也不能挂死
_UPDATE_WAIT_MS = 60_000


def main() -> int:
    setup_logging()
    log = get_logger("smoke")
    log.info("{} v{} 冒烟测试", APP_NAME, __version__)

    init_i18n()
    init_db()

    qt_app = QApplication(sys.argv)
    # 关掉"最后一个窗口关闭就退出" —— 否则 A 一关窗 exec() 当场返回, 下面 B 那一
    # 段根本跑不到 (这个洞让 B 静悄悄地没被测到过)。退出由末尾的 quit() 说了算。
    qt_app.setQuitOnLastWindowClosed(False)

    # ---------- A: 更新线程还在跑时关窗 ----------
    # 直接 qt_app.quit() 会**绕过 closeEvent**, 收尾逻辑 (停下载线程、掐掉自更新
    # 子进程) 一条都测不到 —— 所以这里必须真·关窗。
    window_a = MainWindow()
    window_a.show()

    # ---------- B: 更新线程跑完之后关窗 ----------
    def phase_b() -> None:
        log.info("[A] 关窗未崩 (更新线程在跑时)")
        window_b = MainWindow()
        window_b.show()

        done = False

        def close_b() -> None:
            nonlocal done
            if done:
                return
            done = True
            # 隔一拍再关: deleteLater 是往事件循环里投递 DeferredDelete, 不是当场
            # 析构。不等这一拍, QThread 还活着, B 这条路根本没走到。
            QTimer.singleShot(300, window_b.close)
            QTimer.singleShot(1200, lambda: log.info("[B] 关窗未崩 (更新线程已结束)"))
            QTimer.singleShot(1500, qt_app.quit)

        thread = getattr(window_b, "_update_thread", None)
        if thread is None:  # 已经跑完了 (probe 有缓存, 可能很快)
            close_b()
        else:
            thread.finished.connect(close_b)
            QTimer.singleShot(_UPDATE_WAIT_MS, close_b)  # 兜底, 别挂死

    QTimer.singleShot(1500, window_a.close)
    QTimer.singleShot(2500, phase_b)

    exit_code = qt_app.exec()
    log.info("冒烟测试结束 code={}", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
