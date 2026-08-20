"""国际化: zh-CN / en-US.

启动时读 config.ui.language, 整个 session 用一种语言。

新增字符串: 在下方 STRINGS 的两种语言里都加上对应 key。
UI 里禁止硬编码字面值, 一律走 t("key")。
"""
from __future__ import annotations

from typing import Final

from app.infra.config import load_config

LANGUAGES: Final = ("zh-CN", "en-US")
DEFAULT_LANGUAGE: Final = "zh-CN"

STRINGS: Final[dict[str, dict[str, str]]] = {
    "zh-CN": {
        # ---- 页面 ----
        "page.downloader.title": "视频下载",
        "page.downloader.subtitle": "YouTube → MP4 / MP3, 最多 2 个并发",
        # ---- 链接输入 ----
        "downloader.url.label": "YouTube 链接:",
        "downloader.url.placeholder": "粘贴 youtube.com/watch?v=...",
        "downloader.url.paste": "📋 粘贴",
        "downloader.url.stripped": "⚠ 已自动剥离播放列表参数: {keys}",
        # ---- 下载选项 ----
        "downloader.format.label": "格式:",
        "downloader.format.mp4": "MP4 视频",
        "downloader.format.mp3": "MP3 音频",
        "downloader.quality.video": "画质:",
        "downloader.quality.audio": "音质:",
        "downloader.output.dir": "保存到:",
        "common.browse": "浏览...",
        "downloader.add": "▶ 加入下载队列",
        # ---- 队列 ----
        "downloader.queue.label": "下载队列",
        "downloader.queue.empty": "队列为空, 粘贴 URL 后点 \"加入下载队列\"",
        "downloader.job.cancel": "⏹ 取消",
        "downloader.job.open": "📂 打开",
        "downloader.job.remove": "✕ 移除",
        "downloader.job.retry": "⟳ 重试",
        "downloader.job.retrying": "⟳ 链接失效, 重试 {n}/{total}...",
        "downloader.job.status.queued": "⏳ 等待中",
        "downloader.job.status.running": "▶ 下载中",
        "downloader.job.status.done": "✓ 完成",
        "downloader.job.status.error": "❌ 失败",
        "downloader.job.status.cancelled": "⏹ 已取消",
        # ---- 错误 ----
        "downloader.error.title": "下载失败",
        "downloader.error.no_url": "请先粘贴 YouTube 链接",
        "downloader.error.no_ffmpeg": "缺少 ffmpeg, 无法合并音视频。\n请重新安装本程序 (安装包自带 ffmpeg), 或联系 IT。",
        # ---- 本分支新增 ----
        "downloader.error.no_dir": "请先选择保存位置",
        "downloader.error.bad_dir": "无法使用这个保存位置:\n{dir}\n\n{err}",
        "status.ffmpeg": "ffmpeg",
        "status.jsruntime": "JS 运行时",
    },
    "en-US": {
        # ---- 页面 ----
        "page.downloader.title": "Video Downloader",
        "page.downloader.subtitle": "YouTube → MP4 / MP3, max 2 concurrent",
        # ---- 链接输入 ----
        "downloader.url.label": "YouTube URL:",
        "downloader.url.placeholder": "Paste youtube.com/watch?v=...",
        "downloader.url.paste": "📋 Paste",
        "downloader.url.stripped": "⚠ Playlist params auto-stripped: {keys}",
        # ---- 下载选项 ----
        "downloader.format.label": "Format:",
        "downloader.format.mp4": "MP4 video",
        "downloader.format.mp3": "MP3 audio",
        "downloader.quality.video": "Video quality:",
        "downloader.quality.audio": "Audio bitrate:",
        "downloader.output.dir": "Save to:",
        "common.browse": "Browse...",
        "downloader.add": "▶ Add to queue",
        # ---- 队列 ----
        "downloader.queue.label": "Download queue",
        "downloader.queue.empty": "Queue is empty. Paste a URL and click \"Add to queue\"",
        "downloader.job.cancel": "⏹ Cancel",
        "downloader.job.open": "📂 Open",
        "downloader.job.remove": "✕ Remove",
        "downloader.job.retry": "⟳ Retry",
        "downloader.job.retrying": "⟳ Link expired, retrying {n}/{total}...",
        "downloader.job.status.queued": "⏳ Queued",
        "downloader.job.status.running": "▶ Downloading",
        "downloader.job.status.done": "✓ Done",
        "downloader.job.status.error": "❌ Failed",
        "downloader.job.status.cancelled": "⏹ Cancelled",
        # ---- 错误 ----
        "downloader.error.title": "Download failed",
        "downloader.error.no_url": "Please paste a YouTube URL first",
        "downloader.error.no_ffmpeg": "ffmpeg is missing, so audio and video cannot be merged.\nPlease reinstall this app (the installer bundles ffmpeg) or contact IT.",
        # ---- 本分支新增 ----
        "downloader.error.no_dir": "Choose a save location first",
        "downloader.error.bad_dir": "Cannot use this save location:\n{dir}\n\n{err}",
        "status.ffmpeg": "ffmpeg",
        "status.jsruntime": "JS runtime",
    },
}

_current: str = DEFAULT_LANGUAGE


def init_i18n() -> str:
    """启动时调用: 从 config 读语言并锁定本次 session. 返回生效的语言码."""
    global _current
    lang = (load_config().get("ui") or {}).get("language", DEFAULT_LANGUAGE)
    _current = lang if lang in LANGUAGES else DEFAULT_LANGUAGE
    return _current


def current_language() -> str:
    return _current


def t(key: str) -> str:
    """查表; 缺失时回落到中文, 再缺就把 key 原样返回 (方便一眼看出漏了哪条)."""
    table = STRINGS.get(_current, STRINGS[DEFAULT_LANGUAGE])
    if key in table:
        return table[key]
    return STRINGS[DEFAULT_LANGUAGE].get(key, key)
