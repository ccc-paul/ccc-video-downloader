"""模块 2 核心: yt-dlp Python API 封装 (设计文档 §4.4).

纯 Python, 无 PyQt 依赖. 调用方负责传 progress_hook (UI 那端会接 pyqtSignal).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import yt_dlp

from app.infra import jsruntime
from app.infra.logger import get_logger

log = get_logger("download")

# YouTube URL 上和单视频无关的参数, 会让 yt-dlp 把整个播放列表拖下来 (legacy 教训).
_PLAYLIST_PARAMS_TO_STRIP = ("list", "index", "start_radio", "pp")

# yt-dlp 的报错信息自带终端着色 (形如 "\x1b[0;31mERROR:\x1b[0m ..."), 直接
# str(e) 塞进 Qt 标签会显示成一串乱码方块 (2026-08-16 截图实见). 落 UI 前先洗掉。
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

FormatKind = Literal["mp4", "mp3"]


class _YdlLogger:
    """把 yt-dlp 的输出转进 loguru. yt-dlp 只要求有 debug/warning/error 三个方法.

    debug 降级成 loguru 的 debug (量很大), warning/error 原样保留 —— 这些正是
    "为什么 403" 的线索来源。
    """

    def debug(self, msg: str) -> None:
        # yt-dlp 把普通输出也走 debug, 前缀 [debug] 的才是真调试信息
        log.debug(msg.removeprefix("[debug] "))

    def info(self, msg: str) -> None:
        log.debug(msg)

    def warning(self, msg: str) -> None:
        log.warning("yt-dlp: {}", msg)

    def error(self, msg: str) -> None:
        log.error("yt-dlp: {}", msg)


@dataclass(frozen=True)
class DownloadOptions:
    format_kind: FormatKind
    quality: str            # mp4: "480" / "720" / "1080" / "1440" / "best" ; mp3: "128" / "192" / "320"
    output_dir: Path
    filename_template: str = "%(title)s - %(uploader)s.%(ext)s"
    ffmpeg_location: Path | None = None  # 目录, 不是 exe


def strip_ansi(text: str) -> str:
    """去掉 yt-dlp 报错里的 ANSI 颜色码, 供 UI 显示."""
    return _ANSI_RE.sub("", text).strip()


def clean_url(url: str) -> tuple[str, list[str]]:
    """剥离播放列表相关 query 参数. 返回 (clean_url, stripped_keys)."""
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        return url.strip(), []
    qs = parse_qs(parsed.query, keep_blank_values=True)
    stripped = [k for k in _PLAYLIST_PARAMS_TO_STRIP if k in qs]
    for k in stripped:
        qs.pop(k, None)
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query)), stripped


def build_ydl_opts(options: DownloadOptions, progress_hook: Callable[[dict], None]) -> dict:
    """把 UI 选项映射成 YoutubeDL kwargs (设计文档 §4.4 选项表)."""
    opts: dict = {
        "outtmpl": str(options.output_dir / options.filename_template),
        "progress_hooks": [progress_hook],
        "noprogress": True,
        "quiet": True,
        # 不再设 no_warnings —— yt-dlp 的警告是诊断 403 的关键线索
        # ("没有 JS 运行时" 就是靠它才发现的), 交给 logger 收进日志文件.
        "logger": _YdlLogger(),
        "noplaylist": True,  # 双保险, URL 即使没清干净也只拉单视频
    }
    if options.ffmpeg_location:
        opts["ffmpeg_location"] = str(options.ffmpeg_location)

    # YouTube 的 nsig / 签名挑战要靠 JS 运行时算; 没有的话 yt-dlp 退回
    # android_vr 等客户端, 直链容易 403、清晰度也变少 (2026-08 踩过).
    runtimes = jsruntime.js_runtimes_opt()
    if runtimes:
        opts["js_runtimes"] = runtimes
        # 光有运行时不够, 还要允许拉 EJS 挑战求解脚本 (GitHub, 自动缓存),
        # 否则日志里会是 "n challenge solving failed: Some formats may be missing".
        opts["remote_components"] = ["ejs:github"]

    if options.format_kind == "mp4":
        q = options.quality
        if q == "best":
            opts["format"] = "bestvideo+bestaudio/best"
        else:
            opts["format"] = (
                f"bestvideo[height<={q}][ext=mp4]+bestaudio[ext=m4a]/"
                f"best[height<={q}]"
            )
        opts["merge_output_format"] = "mp4"
    elif options.format_kind == "mp3":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": options.quality,
        }]
    else:  # pragma: no cover -- guarded by Literal type
        raise ValueError(f"unsupported format: {options.format_kind}")

    return opts


def with_ffmpeg(options: DownloadOptions, ffmpeg_dir: Path) -> DownloadOptions:
    """便利函数: 给 options 注入 ffmpeg 路径."""
    return replace(options, ffmpeg_location=ffmpeg_dir)


def extract_info(url: str) -> dict:
    """只取 metadata, 不下载. 抛出 yt_dlp.DownloadError 失败."""
    opts: dict = {
        "quiet": True,
        "noprogress": True,
        "noplaylist": True,
        "logger": _YdlLogger(),
    }
    runtimes = jsruntime.js_runtimes_opt()
    if runtimes:
        opts["js_runtimes"] = runtimes
        opts["remote_components"] = ["ejs:github"]
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)
