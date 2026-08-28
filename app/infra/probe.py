"""探测外部可执行文件是否**真的能跑**, 而不只是文件存在.

背景 (2026-08-21): 有台装了安装包的机器下载一直 403, 但状态栏 ffmpeg / JS 运行时
两个点都是亮的 —— 因为当时只检查了 `Path.exists()`。文件在 ≠ 能执行:
杀毒软件拦截、缺 VC++ 运行库、文件被隔离/损坏, 都会让它存在但起不来。
deno 是个 93MB 的无签名二进制, 被 AV 拦下并不稀奇。

所以这里真的去跑一下 `--version`, 把结果记进日志、也让状态栏显示真相。
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

# Windows 无控制台程序里起子进程会闪一个黑窗口, 用这个标志压掉
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# 还在跑的探测/更新子进程. 关窗时要能把它们杀掉 —— 否则后台线程还阻塞在
# communicate() 上, QThread 带着未结束的线程被销毁, 进程直接 abort。
# mac 上尤其明显: 一次 --version 就要 8~12s, 用户点关闭时它多半还没跑完。
_live: set[subprocess.Popen] = set()

# 关窗后不许再起新的子进程。**光杀当前那个不够**: 后台线程是"探版本 → 自更新"两步走,
# 杀掉探测它扭头就去起更新进程, 又是一次长阻塞, 关窗照样等不到线程退出。
_cancelled = False


def kill_running() -> None:
    """杀掉在跑的探测/更新子进程, 并禁掉后续的. 关窗路径专用, 不抛异常.

    **必须整个进程组一起杀**: yt-dlp 的官方包是 PyInstaller onefile, 跑起来是
    "引导进程 + 解包出来的真身"两层。只 kill 父进程的话, 孙进程还攥着 stdout 管道,
    communicate() 照样阻塞 —— 关窗还是等不到线程退出。
    """
    global _cancelled
    _cancelled = True
    for proc in list(_live):
        try:
            if sys.platform == "win32":
                proc.kill()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                proc.kill()
            except OSError:
                pass


def is_cancelled() -> bool:
    """关窗流程是否已经把子进程掐了.

    调用方要用它把"取消"和"真故障"分开 —— 取消是我们自己干的, 不是 yt-dlp 坏了,
    不该写进缓存, 更不该拿去当版本号往日志和状态栏上报。
    """
    return _cancelled


def run_version(exe: Path, *args: str, timeout: float = 8.0) -> tuple[bool, str]:
    """跑 `exe args` 并取首行输出. 返回 (是否成功, 版本串或失败原因).

    只用于启动自检和诊断, 失败**不抛异常** —— 探测本身不该让程序起不来。
    进程会登记进 `_live`, 关窗时 `kill_running()` 能把它掐掉。
    """
    if _cancelled:
        return False, "已取消"

    proc = None
    try:
        proc = subprocess.Popen(
            [str(exe), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=_CREATE_NO_WINDOW,
            # 自成一个进程组, 这样 kill_running() 能连 onefile 解包出来的
            # 孙进程一起收掉 (Windows 上 Popen 没这个参数, 靠 kill 即可)
            start_new_session=sys.platform != "win32",
        )
        _live.add(proc)
        stdout, stderr = proc.communicate(timeout=timeout)
    except FileNotFoundError:
        return False, "文件不存在"
    except PermissionError:
        # 典型是杀毒软件拦截, 或文件没有执行权限
        return False, "无法执行 (权限被拒, 可能被杀毒软件拦截)"
    except subprocess.TimeoutExpired:
        proc.kill()
        return False, f"执行超时 (>{timeout:.0f}s)"
    except OSError as e:
        return False, f"无法执行: {e}"
    finally:
        if proc is not None:
            _live.discard(proc)

    # 负数 = 被信号打死, 正常就是关窗时 kill_running() 掐的。别报成"不可用",
    # 那会在日志里留下一条吓人的假故障 (实测: "不可用 —— 退出码 -9")
    if proc.returncode is None or proc.returncode < 0:
        return False, "已取消"

    output = (stdout or stderr or "").strip().splitlines()
    first = output[0] if output else ""
    if proc.returncode != 0 and not first:
        return False, f"退出码 {proc.returncode}"
    return True, first
