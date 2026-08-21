"""ffmpeg 路径解析: 优先项目 vendor/, 回落到系统 PATH. 跨平台.

yt-dlp 的 ffmpeg_location 参数要的是**目录**, 不是 exe 路径.
Windows 的可执行文件名是 ffmpeg.exe, mac/Linux 是 ffmpeg.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from app.infra.probe import run_version

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_EXE_NAME = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
_VENDOR_EXE = _PROJECT_ROOT / "vendor" / "ffmpeg" / _EXE_NAME


def find_ffmpeg() -> Path | None:
    """返回 ffmpeg 可执行文件全路径, 找不到返回 None."""
    if _VENDOR_EXE.exists():
        return _VENDOR_EXE
    sys_path = shutil.which("ffmpeg")
    if sys_path:
        return Path(sys_path)
    return None


def ffmpeg_dir() -> Path | None:
    """yt-dlp 用的目录形式. 找不到返回 None."""
    exe = find_ffmpeg()
    return exe.parent if exe else None


def probe() -> tuple[bool, str]:
    """真的跑一下 ffmpeg, 返回 (可用, 版本串或失败原因). 同 jsruntime.probe 的道理:
    文件存在不代表能执行 (杀毒拦截 / 缺运行库 / 文件损坏)."""
    exe = find_ffmpeg()
    if exe is None:
        return False, "未找到"
    ok, detail = run_version(exe, "-version")
    return ok, (detail if ok else f"{exe} — {detail}")


def is_available() -> bool:
    """能否真正用于合并音视频 (跑得起来才算)."""
    return probe()[0]
