"""配置读写: 应用数据目录下的 config.json.

这个工具**没有设置页** —— config 只用来记住用户上次选的东西 (保存目录、格式、
画质、界面语言), 下次打开还是那套, 免得每次重填。

数据目录按平台解析:
- Windows: %APPDATA%\\VideoDownloader
- macOS:   ~/Library/Application Support/VideoDownloader
- Linux:   $XDG_DATA_HOME/VideoDownloader 或 ~/.local/share/VideoDownloader
"""
from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from app import APP_FOLDER


def _resolve_data_dir() -> Path:
    """跨平台应用数据根目录 (不含 APP 子目录)."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


APPDATA_DIR = _resolve_data_dir() / APP_FOLDER
CONFIG_PATH = APPDATA_DIR / "config.json"


def default_download_dir() -> Path:
    """首次运行时的保存目录: 系统的视频文件夹, 没有就回落用户主目录.

    各平台的名字不一样 —— macOS 是 Movies 而不是 Videos, 写死 "Videos" 的话
    Mac 上会一路回落到主目录, 下载就散在 ~ 底下了。
    """
    home = Path.home()
    candidate = home / ("Movies" if sys.platform == "darwin" else "Videos")
    return candidate if candidate.is_dir() else home


DEFAULT_CONFIG: dict[str, Any] = {
    "version": "1.0.0",
    # 上次用的下载选项 —— 关掉程序再打开还是这套
    "download": {
        "output_dir": "",       # 空 = 用 default_download_dir()
        "format_kind": "mp4",
        "video_quality": "1080",
        "audio_quality": "192",
    },
    "ui": {
        "language": "zh-CN",
    },
}


def ensure_appdata_dir() -> Path:
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    return APPDATA_DIR


def load_config() -> dict[str, Any]:
    """读 config.json; 不存在或损坏都返回默认值的深拷贝 (不写盘).

    损坏也要能起来 —— 这是给非技术同事用的工具, 不能因为一个 JSON 语法错误
    就打不开; 大不了回到默认设置。
    """
    if not CONFIG_PATH.exists():
        return deepcopy(DEFAULT_CONFIG)
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return deepcopy(DEFAULT_CONFIG)


def save_config(cfg: dict[str, Any]) -> None:
    ensure_appdata_dir()
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def remember_download_options(
    *, output_dir: str, format_kind: str, video_quality: str, audio_quality: str
) -> None:
    """把当前选项写回 config, 供下次启动恢复. 失败只记日志, 不打断下载."""
    from app.infra.logger import get_logger

    cfg = load_config()
    cfg.setdefault("download", {}).update({
        "output_dir": output_dir,
        "format_kind": format_kind,
        "video_quality": video_quality,
        "audio_quality": audio_quality,
    })
    try:
        save_config(cfg)
    except OSError as e:
        get_logger("config").warning("保存选项失败: {}", e)
