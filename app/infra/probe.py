"""探测外部可执行文件是否**真的能跑**, 而不只是文件存在.

背景 (2026-08-21): 有台装了安装包的机器下载一直 403, 但状态栏 ffmpeg / JS 运行时
两个点都是亮的 —— 因为当时只检查了 `Path.exists()`。文件在 ≠ 能执行:
杀毒软件拦截、缺 VC++ 运行库、文件被隔离/损坏, 都会让它存在但起不来。
deno 是个 93MB 的无签名二进制, 被 AV 拦下并不稀奇。

所以这里真的去跑一下 `--version`, 把结果记进日志、也让状态栏显示真相。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Windows 无控制台程序里起子进程会闪一个黑窗口, 用这个标志压掉
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def run_version(exe: Path, *args: str, timeout: float = 8.0) -> tuple[bool, str]:
    """跑 `exe args` 并取首行输出. 返回 (是否成功, 版本串或失败原因).

    只用于启动自检和诊断, 失败**不抛异常** —— 探测本身不该让程序起不来。
    """
    try:
        proc = subprocess.run(
            [str(exe), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        return False, "文件不存在"
    except PermissionError:
        # 典型是杀毒软件拦截, 或文件没有执行权限
        return False, "无法执行 (权限被拒, 可能被杀毒软件拦截)"
    except subprocess.TimeoutExpired:
        return False, f"执行超时 (>{timeout:.0f}s)"
    except OSError as e:
        return False, f"无法执行: {e}"

    output = (proc.stdout or proc.stderr or "").strip().splitlines()
    first = output[0] if output else ""
    if proc.returncode != 0 and not first:
        return False, f"退出码 {proc.returncode}"
    return True, first
