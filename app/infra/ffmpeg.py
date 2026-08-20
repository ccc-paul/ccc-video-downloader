"""ffmpeg 路径解析: 优先项目 vendor/, 回落到系统 PATH. 跨平台.

yt-dlp 的 ffmpeg_location 参数要的是**目录**, 不是 exe 路径.
Windows 的可执行文件名是 ffmpeg.exe, mac/Linux 是 ffmpeg.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

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


def is_available() -> bool:
    return find_ffmpeg() is not None
