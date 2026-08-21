"""JavaScript 运行时解析: 优先项目 vendor/, 回落系统 PATH.

**为什么模块 2 需要 JS 运行时**：YouTube 用 JS 算 nsig / 签名挑战。yt-dlp 自
2026 年起把"无 JS 运行时"的提取路径标记为 deprecated —— 没有运行时就只能退回
`android vr` 等客户端，拿到的直链**容易 403 Forbidden**，能选的清晰度也变少。

链条要两环齐全才算数：

1. **JS 运行时**（本模块负责）—— deno / node / quickjs / bun，优先级从高到低
2. **EJS 挑战求解脚本** —— 由 yt-dlp 在需要时从 GitHub 拉取并缓存，
   要显式允许 (`remote_components=['ejs:github']`)，见 [ytdlp_wrapper.build_ydl_opts]

只有 1 而没有 2 时，日志里会看到 `n challenge solving failed: Some formats may be missing`。

结构与 [ffmpeg.py](ffmpeg.py) 保持一致 (vendor 优先 → PATH 回落), 打包时
vendor/deno 会被复制进 PyInstaller dist。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from app.infra.probe import run_version

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# yt-dlp 支持的运行时, 按它自己的优先级排 (高 → 低)
_RUNTIMES = ("deno", "node", "quickjs", "bun")

_EXE_SUFFIX = ".exe" if sys.platform == "win32" else ""


def _vendor_exe(name: str) -> Path:
    return _PROJECT_ROOT / "vendor" / name / f"{name}{_EXE_SUFFIX}"


def find_js_runtime() -> tuple[str, Path] | None:
    """返回 (运行时名, 可执行文件路径); 都找不到返回 None.

    先按优先级找 vendor/, 再按优先级找系统 PATH —— vendor 里的版本是我们验证过的,
    优先于用户机器上可能很老的全局安装。
    """
    for name in _RUNTIMES:
        exe = _vendor_exe(name)
        if exe.exists():
            return name, exe
    for name in _RUNTIMES:
        found = shutil.which(name)
        if found:
            return name, Path(found)
    return None


def probe() -> tuple[bool, str]:
    """真的跑一下运行时, 返回 (可用, 版本串或失败原因).

    **不要用"文件存在"当可用性判据** —— deno 是个 93MB 的无签名二进制, 很容易
    被杀毒软件拦住执行; 那时文件在、状态灯亮, 但下载全部 403 (2026-08 实际事故)。
    """
    found = find_js_runtime()
    if found is None:
        return False, "未找到 (deno / node / bun 都没有)"
    name, exe = found
    ok, detail = run_version(exe, "--version")
    return ok, (f"{name} {detail}" if ok else f"{name} @ {exe} — {detail}")


def is_available() -> bool:
    """能否真正用于解签名挑战 (跑得起来才算)."""
    return probe()[0]


def js_runtimes_opt() -> dict | None:
    """拼成 yt-dlp 要的 `js_runtimes` 参数: {'deno': {'path': '...'}}.

    找不到返回 None —— 调用方应当**不传**这个 key, 让 yt-dlp 走它自己的默认
    (只启用 deno 并在 PATH 里找), 而不是传一个空 dict 把默认也关掉。
    """
    found = find_js_runtime()
    if found is None:
        return None
    name, exe = found
    return {name: {"path": str(exe)}}
