r"""定位 yt-dlp 可执行文件, 并维护一份**用户可写**的副本供自更新.

## 为什么不再用 yt-dlp 的 Python 库

YouTube 每隔几周换一次播放器, 旧版 yt-dlp 立刻全线 403 (2026-08-21 就这么翻车过)。
而 PyInstaller 把纯 Python 模块编译进 exe 内嵌的 PYZ 归档 —— 装进去的 yt-dlp
既没有 site-packages 可 pip 升级, 外部副本也抢不过 FrozenImporter, 等于**冻死**在
打包那一刻。

改用官方 standalone `yt-dlp.exe` + 子进程调用后:

- 更新 = 换一个文件, 它自带 `-U` 自更新
- 命令行接口比 Python API 稳定得多, 不会因为库改签名把程序改崩
- 它自带解释器, 不受本程序 Python 3.11 的版本限制

## 为什么要复制到 APPDATA

程序可能装在 `C:\Program Files\` 下 (写要管理员权限), 自更新会失败。所以启动时
把随包的基线版本复制到 `%APPDATA%\VideoDownloader\bin\`, 之后一律用那一份 ——
它在用户目录下, `-U` 想怎么写就怎么写。

随包版本比 APPDATA 里的**新**时也会覆盖 (用户装了新版程序, 不该还跑旧 yt-dlp)。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from app.infra.config import APPDATA_DIR
from app.infra.logger import get_logger
# run_version 单独引进来是为了能被测试 monkeypatch; 模块本身也要, 用来问取消状态
from app.infra import probe as _probe
from app.infra.probe import run_version

log = get_logger("ytdlp")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_EXE_NAME = "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"

# 随安装包分发的基线版本 (只读, 可能在 Program Files 下)
_BUNDLED = _PROJECT_ROOT / "vendor" / "ytdlp" / _EXE_NAME
# 实际使用的可写副本
_MANAGED_DIR = APPDATA_DIR / "bin"
_MANAGED = _MANAGED_DIR / _EXE_NAME


def bundled_path() -> Path | None:
    return _BUNDLED if _BUNDLED.is_file() else None


def managed_path() -> Path | None:
    return _MANAGED if _MANAGED.is_file() else None


def ensure_managed_copy() -> Path | None:
    """确保 APPDATA 下有一份可写副本, 返回它的路径; 都没有则返回 None.

    复制时机: 副本不存在, 或随包版本更新 (按 mtime 判, 够用且不必启动 exe 问版本)。
    复制失败不致命 —— 回落用随包那份, 只是不能自更新。
    """
    bundled = bundled_path()
    if bundled is None:
        return managed_path()

    try:
        need_copy = not _MANAGED.is_file() or (
            bundled.stat().st_mtime > _MANAGED.stat().st_mtime
        )
        if need_copy:
            _MANAGED_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled, _MANAGED)
            log.info("已把随包的 yt-dlp 复制到可写位置: {}", _MANAGED)
    except OSError as e:
        log.warning("复制 yt-dlp 到 {} 失败, 将直接用随包那份: {}", _MANAGED_DIR, e)
        return bundled
    return _MANAGED


def find_ytdlp() -> Path | None:
    """返回该用的 yt-dlp 路径: 可写副本 → 随包 → 系统 PATH."""
    managed = ensure_managed_copy()
    if managed and managed.is_file():
        return managed
    found = shutil.which("yt-dlp")
    return Path(found) if found else None


# mac 上官方发布的 yt-dlp 是 PyInstaller **onefile**: 每次执行都要把 ~37MB 解到
# 临时目录再跑, 实测 `--version` 单次要 8~12s (同一台机器 deno 0.05s / ffmpeg 0.01s
# —— 静态二进制没这个开销)。默认 8s 超时在 mac 上必然误报"不可用", 所以放宽。
# Windows 的 yt-dlp.exe 同样是 onefile, 但实测快得多, 沿用默认值。
_PROBE_TIMEOUT = 30.0 if sys.platform == "darwin" else 8.0

# probe 结果缓存: 启动时日志和状态栏都要问版本, mac 上问一次就是 8~12s,
# 问两次等于白等一倍。自更新完成后用 refresh=True 拿新版本号。
_probe_cache: tuple[bool, str] | None = None


def probe(refresh: bool = False) -> tuple[bool, str]:
    """跑一下拿版本号. 文件存在不代表能执行 (杀毒拦截 / 文件损坏)."""
    global _probe_cache
    if _probe_cache is not None and not refresh:
        return _probe_cache

    exe = find_ytdlp()
    if exe is None:
        result = (False, "未找到 yt-dlp")
    else:
        result = run_version(exe, "--version", timeout=_PROBE_TIMEOUT)

    # 关窗掐掉的探测不是探测结果, 不许进缓存 —— 否则"已取消"会顶掉上一次探到的
    # 真版本号, 状态栏和日志跟着报一条假故障 (实测: "yt-dlp: 不可用 —— 已取消")
    if _probe.is_cancelled():
        return _probe_cache or result

    _probe_cache = result
    return _probe_cache


def is_available() -> bool:
    return probe()[0]


def self_update(timeout: float = 120.0) -> tuple[bool, str]:
    """让 yt-dlp 自己更新到最新稳定版. 返回 (是否更新了, 说明文字).

    这是整套「外挂二进制」设计的目的所在: 用户不必等我们重打安装包, 程序自己就能
    跟上 YouTube 的变化。

    **只更新 APPDATA 里那份副本** —— 随包那份可能在 Program Files 下, 写不动。
    失败一律不致命: 网络不通、被杀毒拦、公司代理挡住 GitHub, 都只是"没更新成",
    照样用现在这份继续下载。
    """
    exe = find_ytdlp()
    if exe is None:
        return False, "未找到 yt-dlp, 跳过更新"

    # before 走缓存: 启动时刚探过一次, mac 上再问一次又是 8~12s
    before = probe()[1]
    ok, detail = run_version(exe, "--update-to", "stable", timeout=timeout)
    if not ok:
        if _probe.is_cancelled():
            return False, "更新被关窗打断, 下次启动再更新"
        return False, f"更新失败 (不影响使用): {detail}"

    after = probe(refresh=True)[1]
    if _probe.is_cancelled():
        # 更新本身可能已经成了, 但版本号问不到了。**别把"已取消"当版本号往外报** ——
        # 会拼出 "yt-dlp 已更新: 2026.08.19 → 已取消" 这种自相矛盾的日志。
        return False, "更新被关窗打断, 下次启动再更新"
    if after and after != before:
        return True, f"yt-dlp 已更新: {before} → {after}"
    return False, f"yt-dlp 已是最新 ({after or before})"
