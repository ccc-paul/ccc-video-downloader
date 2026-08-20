"""跨平台桌面集成: 在系统文件管理器里打开文件夹/定位文件.

Windows→explorer / os.startfile, macOS→open, Linux→xdg-open.
core 层禁止 import PyQt6, 这里只用标准库, 可独立测试.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.infra.logger import get_logger

log = get_logger("desktop")


def open_in_file_manager(path: Path | str) -> bool:
    """在系统文件管理器里打开 path (目录则打开它, 文件则打开所在目录).

    成功返回 True; 平台不支持或调用失败返回 False (不抛异常, 让调用方决定如何提示).
    """
    p = Path(path)
    target = p if p.is_dir() else p.parent
    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(target)], check=False)
        else:
            subprocess.run(["xdg-open", str(target)], check=False)
        return True
    except Exception as e:  # noqa: BLE001 — 便利功能, 失败不影响主流程
        log.warning("打开文件管理器失败: {} ({})", target, e)
        return False


def reveal_in_file_manager(path: Path | str) -> bool:
    """在文件管理器里定位并选中某个文件 (Windows explorer /select, macOS open -R).

    文件不存在时回落到打开其父目录. Linux 无统一 "选中" 协议, 直接打开父目录.
    成功返回 True, 失败返回 False (不抛异常).
    """
    p = Path(path)
    try:
        if not p.exists():
            return open_in_file_manager(p.parent) if p.parent.exists() else False
        if sys.platform == "win32":
            # 坑: explorer /select 必须用单条命令行字符串 `/select,"路径"` (逗号紧挨引号).
            # 用 list 形式 ["explorer", "/select,<带空格路径>"] 会被当成一个含空格 token,
            # explorer 解析失败会默默打开"文档"目录 —— 文件名含空格时必现.
            # explorer 退出码语义特殊, 不能用 check=True.
            subprocess.run(f'explorer /select,"{p}"', check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(p)], check=False)
        else:
            return open_in_file_manager(p.parent)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("定位文件失败: {} ({})", p, e)
        return False
