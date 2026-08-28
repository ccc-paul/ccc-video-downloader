"""模块 2 核心: 组装 yt-dlp **命令行**参数, 并解析它的输出.

2026-08-21 从 Python API 改为子进程调用, 原因见 [ytdlp_bin.py](../infra/ytdlp_bin.py)
的模块说明 —— 一句话: 打包后 Python 库冻死在 exe 里没法更新, 而 YouTube 每隔几周
就换播放器把旧版打废。命令行接口既能随时换二进制, 也比 Python API 稳定。

本模块纯字符串处理, 不起进程、不依赖 PyQt, 可独立测试。
起进程和读输出在 [download_service.py](../services/download_service.py)。

## 输出协议

靠 yt-dlp 的 `--print` / `--progress-template` 打上自定义前缀, 再逐行认领:

    @@T@@标题|上传者|时长        —— 提取完成 (下载开始前)
    @@P@@已下字节|总字节|估算总字节|速度|ETA
    @@F@@最终文件路径|height|abr|resolution   —— 落盘完成

前缀用 `@@X@@` 这种不可能出现在正常输出里的形式, 免得和视频标题里的字符撞上。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, NamedTuple
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from app.infra import jsruntime

# YouTube URL 上和单视频无关的参数, 会让 yt-dlp 把整个播放列表拖下来 (legacy 教训).
_PLAYLIST_PARAMS_TO_STRIP = ("list", "index", "start_radio", "pp")

# yt-dlp 的报错信息可能自带终端着色, 直接塞进 Qt 标签会显示成一串乱码方块.
# 已经用 --no-colors 关掉了, 这里作为兜底 (系统 PATH 上的旧版可能不认这个参数).
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

FormatKind = Literal["mp4", "mp3"]

# 输出行前缀
TAG_META = "@@T@@"
TAG_PROGRESS = "@@P@@"
TAG_FILE = "@@F@@"

# yt-dlp 对空字段打印的占位符
_NA = "NA"

# 默认文件名: 标题截 60 字符 + 频道名截 20 字符, 拼出来不超过 ~85 字符。
# `%(title).60s` 是 yt-dlp 的字段截断语法 (就是 Python 的格式化精度)。
#
# 不截的话名字动辄上百字符 —— YouTube 的标题本来就长, 后面还要接频道名, 在访达/
# 资源管理器里根本看不全, 用户原话是"长得惊人" (2026-08-27)。想要更短就在界面上
# 自己起名, 见 sanitize_stem / filename_template_for。
DEFAULT_FILENAME_TEMPLATE = "%(title).60s - %(uploader).20s.%(ext)s"


@dataclass(frozen=True)
class DownloadOptions:
    format_kind: FormatKind
    quality: str            # mp4: "480" / "720" / "1080" / "1440" / "best" ; mp3: "128" / "192" / "320"
    output_dir: Path
    filename_template: str = DEFAULT_FILENAME_TEMPLATE
    ffmpeg_location: Path | None = None  # 目录, 不是 exe


class MetaEvent(NamedTuple):
    title: str
    uploader: str
    duration_sec: int


class ProgressEvent(NamedTuple):
    percent: float          # 0..1; 拿不到总大小时为 0
    speed: str
    eta: str


class FileEvent(NamedTuple):
    path: Path
    quality: str            # 实际下到的画质: mp4=分辨率 / mp3=码率


def strip_ansi(text: str) -> str:
    """去掉 ANSI 颜色码, 供 UI 显示."""
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


# ---------- 自定义文件名 ----------

# Windows 的非法字符最多, 一律按它来: \ / : * ? " < > | 再加控制字符。
# mac/Linux 只禁 "/" 和 \0, 但跨平台统一规则更好解释 —— 同一个名字在两边都能用。
_ILLEGAL_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
# Windows 保留设备名 (不分大小写, 带扩展名也算), 建出来的文件打不开
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
# 上限取 100: Windows 整条路径 260 的限制下, 给目录留足余量
MAX_FILENAME_STEM = 100


def sanitize_stem(name: str, max_len: int = MAX_FILENAME_STEM) -> str:
    """把用户输入的文件名洗成安全的主干名 (不含扩展名). 洗不出东西就返回 ""。

    做四件事, 每件都是踩得到的:
    - 去掉路径分隔符和非法字符 —— 否则 "a/b" 会被当成子目录, 甚至写到别处去
    - 去掉用户顺手打的 .mp4 / .mp3 后缀 —— 否则成品是 "片子.mp4.mp4"
    - Windows 保留名加下划线 (CON / NUL / COM1 …), 那些名字建出来的文件打不开
    - 收尾的点和空格在 Windows 上会被悄悄吃掉, 一并去掉; 再按长度截断
    """
    stem = _ILLEGAL_FILENAME_RE.sub("", name)
    # 去掉非法字符后常留下双空格 ("讲道 / 测试" → "讲道  测试"), 收一下
    stem = re.sub(r"\s+", " ", stem).strip()
    for ext in (".mp4", ".mp3"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)].strip()
    stem = stem.strip(". ")
    if stem.upper() in _WIN_RESERVED:
        stem += "_"
    return stem[:max_len].strip(". ")


def filename_template_for(stem: str) -> str:
    """把主干名拼成 yt-dlp 的 -o 模板. 空字符串回落到默认模板。

    **必须转义 %**: yt-dlp 的输出模板里 % 有特殊含义, 用户名字里带一个
    ("50%off") 就会被当成字段开头, 轻则名字错乱重则直接报错。yt-dlp 用 %% 表示字面量。
    """
    if not stem:
        return DEFAULT_FILENAME_TEMPLATE
    return f"{stem.replace('%', '%%')}.%(ext)s"


def unique_stem(output_dir: Path, stem: str, ext: str) -> str:
    """同名文件已存在时补 " (2)" / " (3)" …

    不做这一步的话, yt-dlp 见到同名文件会**跳过下载**并照常报成功 —— 用户给两个
    不同的视频起了同一个名字, 第二个悄悄没下, 队列行还指着第一个的文件。
    """
    if not stem:
        return stem
    candidate = stem
    n = 2
    while (output_dir / f"{candidate}.{ext}").exists():
        candidate = f"{stem} ({n})"
        n += 1
    return candidate


# YouTube 的 H.264 一般只到 1080p, 再往上只有 VP9 / AV1。
_H264_MAX_HEIGHT = 1080


def format_selector(options: DownloadOptions) -> str:
    """按格式/画质拼 -f 表达式.

    **1080p 及以下优先挑 H.264 (avc1)**, 而不是只看容器 —— YouTube 的 AV1 也是装在
    mp4 容器里的, 光写 `[ext=mp4]` 会挑到 `av01`。自己机器上能放 (新款 Mac 硬解 AV1),
    发给同事就是「此文件包含与 QuickTime Player 不兼容的部分媒体」, 文件本身没坏,
    是解不了码 (2026-08-28 实测: 用户发出去的三首歌, 两首是 av01 的都打不开,
    唯一能放的那首恰好是 avc1)。

    1440p / 最佳 不加这个偏好: 那个档位 YouTube 只有 VP9/AV1, 硬要 H.264 等于把用户
    明确要的画质降回 1080p。选到那两档就是画质优先, 代价是老设备可能放不了。
    """
    if options.format_kind == "mp4":
        if options.quality == "best":
            return "bestvideo+bestaudio/best"
        q = options.quality
        if int(q) > _H264_MAX_HEIGHT:
            return f"bestvideo[height<={q}][ext=mp4]+bestaudio[ext=m4a]/best[height<={q}]"
        return (
            # ① H.264 + AAC: 到处都能放
            f"bestvideo[height<={q}][vcodec^=avc1]+bestaudio[ext=m4a]/"
            # ② 这个视频压根没有 H.264 时, 退回原来的挑法 (总比下不了强)
            f"bestvideo[height<={q}][ext=mp4]+bestaudio[ext=m4a]/"
            f"best[height<={q}]"
        )
    if options.format_kind == "mp3":
        return "bestaudio/best"
    raise ValueError(f"unsupported format: {options.format_kind}")


def build_args(options: DownloadOptions, url: str) -> list[str]:
    """组装完整的 yt-dlp 命令行参数 (不含 exe 本身)."""
    args = [
        "--no-playlist",        # 双保险, URL 即使没清干净也只拉单视频
        "--newline",            # 进度逐行输出, 否则是 \r 覆盖同一行, 没法按行解析
        "--no-colors",          # 免得输出里混 ANSI 码
        # **必须显式指定编码**: yt-dlp 往管道写时按系统 ANSI 代码页编码, 且用的是
        # errors='ignore' —— 中文标题会被**整段吃掉**而不是变乱码。实测
        # 「【包教包会】0基础自学3D打印建模教程(1/5)丨…」→「03D(1/5)S01E013D」,
        # 连带 @@F@@ 报的路径也对不上真实文件。
        # 注: 设 PYTHONIOENCODING / PYTHONUTF8 环境变量**没用** —— yt-dlp.exe 是
        # PyInstaller 冻结的, 不吃这两个变量 (2026-08-21 三种方案实测对比过)。
        "--encoding", "utf-8",
        # --print 会**同时**隐含 --simulate 和 --quiet, 两个都得显式关掉:
        # 少了 --no-simulate 就只打印不下载; 少了 --no-quiet 则进度行被整个静音
        # (实测现象: @@T@@ / @@F@@ 都在, 唯独一条 @@P@@ 都没有)
        "--no-simulate",
        "--no-quiet",
        "--progress-template",
        (
            f"download:{TAG_PROGRESS}%(progress.downloaded_bytes)s"
            "|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s"
            "|%(progress._speed_str)s|%(progress._eta_str)s"
        ),
        "--print",
        f"video:{TAG_META}%(title)s|%(uploader)s|%(duration)s",
        "--print",
        f"after_move:{TAG_FILE}%(filepath)s|%(height)s|%(abr)s|%(resolution)s",
        "-o", str(options.output_dir / options.filename_template),
        "-f", format_selector(options),
    ]

    if options.format_kind == "mp4":
        args += ["--merge-output-format", "mp4"]
    else:
        args += ["-x", "--audio-format", "mp3", "--audio-quality", f"{options.quality}K"]

    if options.ffmpeg_location:
        args += ["--ffmpeg-location", str(options.ffmpeg_location)]

    # YouTube 的 nsig / 签名挑战要靠 JS 运行时算; 没有的话 yt-dlp 退回 android_vr
    # 等客户端, 直链容易 403、清晰度也变少 (2026-08 踩过两次)。
    runtime = jsruntime.find_js_runtime()
    if runtime:
        name, exe = runtime
        args += ["--js-runtimes", f"{name}:{exe}"]
        # 光有运行时不够, 还要允许拉 EJS 挑战求解脚本 (GitHub, 自动缓存),
        # 否则日志里会是 "n challenge solving failed: Some formats may be missing".
        args += ["--remote-components", "ejs:github"]

    args.append(url)
    return args


def with_ffmpeg(options: DownloadOptions, ffmpeg_dir: Path) -> DownloadOptions:
    """便利函数: 给 options 注入 ffmpeg 路径."""
    return replace(options, ffmpeg_location=ffmpeg_dir)


# ---------- 输出解析 ----------

def _clean(value: str) -> str:
    """yt-dlp 对空字段打印 'NA'; 统一成空串."""
    value = value.strip()
    return "" if value in (_NA, "None", "") else value


def _as_int(value: str) -> int:
    try:
        return int(float(_clean(value)))
    except (TypeError, ValueError):
        return 0


def parse_meta(line: str) -> MetaEvent | None:
    """认领 @@T@@ 行 —— 提取完成, 标题可用了."""
    if not line.startswith(TAG_META):
        return None
    parts = line[len(TAG_META):].split("|")
    # 标题里可能含 '|', 所以从**右**边取固定的两段, 剩下全算标题
    if len(parts) < 3:
        return MetaEvent(_clean("|".join(parts)), "", 0)
    duration = _as_int(parts[-1])
    uploader = _clean(parts[-2])
    title = _clean("|".join(parts[:-2]))
    return MetaEvent(title, uploader, duration)


def parse_progress(line: str) -> ProgressEvent | None:
    """认领 @@P@@ 行."""
    if not line.startswith(TAG_PROGRESS):
        return None
    parts = line[len(TAG_PROGRESS):].split("|")
    if len(parts) < 5:
        return None
    downloaded = _as_int(parts[0])
    total = _as_int(parts[1]) or _as_int(parts[2])   # total_bytes 拿不到就用估算值
    percent = (downloaded / total) if total else 0.0
    return ProgressEvent(min(percent, 1.0), _clean(parts[3]), _clean(parts[4]))


def parse_file(line: str, format_kind: str) -> FileEvent | None:
    """认领 @@F@@ 行 —— 文件已落盘, 路径和实际画质都在这."""
    if not line.startswith(TAG_FILE):
        return None
    parts = line[len(TAG_FILE):].split("|")
    if len(parts) < 4:
        return None
    # 路径里可能含 '|' (Windows 上不可能, 但别赌), 同样从右边取固定三段
    path = "|".join(parts[:-3])
    height, abr, resolution = parts[-3], parts[-2], parts[-1]

    if format_kind == "mp3":
        quality = f"{_as_int(abr)} kbps" if _as_int(abr) else ""
    else:
        quality = f"{_as_int(height)}p" if _as_int(height) else ""
        if not quality:
            res = _clean(resolution)
            quality = res if res and res != "audio only" else ""
    return FileEvent(Path(_clean(path)), quality)
