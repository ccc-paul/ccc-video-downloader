"""端到端下载验证: 真的起 yt-dlp 子进程拉一个 19 秒视频.

URL 选 "Me at the zoo" -- YouTube 第一支视频, 短小稳定, jawed 频道。
不走 QThread / service, 直接用 core 层拼参数 + 起进程, 验证这条链路是通的:

    ytdlp_bin 找到二进制 → build_args 拼参数 → 子进程 → parse_* 认领输出 → 文件落地

**为什么要有它**: 单测全是纯函数, 拼出来的参数对不对、yt-dlp 认不认、
`@@T@@`/`@@P@@`/`@@F@@` 三种前缀真的会打出来吗 —— 只有真跑一次才知道。
2026-08-21 把 yt-dlp 从 Python 库改成外挂二进制那次, 三个坑
(`--print` 隐含 `--simulate`/`--quiet`、缺 `--encoding utf-8` 中文标题被吃、
少 `--newline` 进度粘成一行) 全是在这一层暴露的。

    python -m tests.e2e_download                 # 默认 mp4 + mp3 都跑
    python -m tests.e2e_download mp4             # 只跑一种
    python -m tests.e2e_download mp3 <URL>       # 换个视频

输出落 output/e2e_download/<kind>/。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.core import ytdlp_wrapper
from app.core.ytdlp_wrapper import DownloadOptions, build_args, clean_url, with_ffmpeg
from app.infra import ytdlp_bin
from app.infra.ffmpeg import ffmpeg_dir, find_ffmpeg
from app.infra.jsruntime import find_js_runtime

TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # Me at the zoo (19s)

# 和 download_service 保持一致: 无控制台程序里起子进程会闪黑窗口
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _download(kind: str, url: str) -> None:
    """跑一趟完整下载并逐项断言. 出错直接抛, 让调用方看见栈."""
    out_dir = Path("output") / "e2e_download" / kind
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*"):
        if stale.is_file():
            stale.unlink()

    options = with_ffmpeg(
        DownloadOptions(
            format_kind=kind,
            quality="720" if kind == "mp4" else "192",
            output_dir=out_dir,
        ),
        ffmpeg_dir(),
    )
    exe = ytdlp_bin.find_ytdlp()
    args = [str(exe), *build_args(options, url)]
    print(f"\n=== {kind} ===")
    print(f"format: {ytdlp_wrapper.format_selector(options)}")

    # stderr 合并进 stdout 按行读 —— 与 download_service._attempt_once 同一套做法,
    # 分开读两个管道容易在一边写满管道缓冲时死锁
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_CREATE_NO_WINDOW,
    )

    meta = file_event = None
    progress_count = 0
    last_error = ""
    for raw in proc.stdout:  # type: ignore[union-attr]
        line = raw.rstrip("\r\n")
        if not line:
            continue
        if (m := ytdlp_wrapper.parse_meta(line)) is not None:
            meta = m
            print(f"  meta: {m.title} / {m.uploader} / {m.duration_sec}s")
        elif (p := ytdlp_wrapper.parse_progress(line)) is not None:
            progress_count += 1
            if progress_count % 20 == 0:
                print(f"  ... {p.percent:.0%}  {p.speed}  ETA {p.eta}")
        elif (f := ytdlp_wrapper.parse_file(line, kind)) is not None:
            file_event = f
            print(f"  file: {f.path.name}  ({f.quality})")
        else:
            clean = ytdlp_wrapper.strip_ansi(line)
            if clean.startswith(("ERROR:", "WARNING:")):
                print(f"  {clean}")
                if clean.startswith("ERROR:"):
                    last_error = clean
    code = proc.wait()

    assert code == 0, f"yt-dlp 退出码 {code}: {last_error}"
    assert meta is not None, "没解析到 @@T@@ 标题行 (--print 参数可能不对)"
    assert meta.title, "标题为空 —— 检查 --encoding utf-8"
    # 少了 --no-quiet 的典型症状: 标题和文件名照常出, 唯独一条进度都没有
    assert progress_count > 0, "一条进度都没有 (--no-quiet / --newline 可能丢了)"
    assert file_event is not None, "没解析到 @@F@@ 输出文件行"
    assert file_event.path.is_file(), f"报了 {file_event.path} 但文件不在"
    assert file_event.path.suffix == f".{kind}", f"扩展名不对: {file_event.path.name}"
    assert file_event.quality, "没拿到实际画质/码率"

    size_kb = file_event.path.stat().st_size / 1024
    assert size_kb > 10, f"文件只有 {size_kb:.1f} KB, 不像下全了"
    print(f"  OK  {file_event.path.name}  {size_kb:.1f} KB  进度回调 {progress_count} 次")


def main() -> int:
    argv = sys.argv[1:]
    kinds = [argv[0]] if argv and argv[0] in ("mp4", "mp3") else ["mp4", "mp3"]
    url = next((a for a in argv if a.startswith("http")), TEST_URL)

    # 三个外部依赖缺哪个都白跑, 先报清楚再说
    exe = ytdlp_bin.find_ytdlp()
    print(f"yt-dlp:    {exe}")
    ok, detail = ytdlp_bin.probe()
    print(f"版本:      {detail if ok else f'不可用 —— {detail}'}")
    print(f"ffmpeg:    {find_ffmpeg()}")
    runtime = find_js_runtime()
    print(f"JS 运行时: {f'{runtime[0]} @ {runtime[1]}' if runtime else '未找到 (很可能 403)'}")
    if exe is None:
        raise SystemExit("没有 yt-dlp 可执行文件, 见 README 的 vendor/ 那一节")
    if find_ffmpeg() is None:
        raise SystemExit("没有 ffmpeg, mp4 分离流合并和 mp3 提取都会失败")

    cleaned, stripped = clean_url(url)
    if stripped:
        print(f"URL 去掉了参数: {stripped}")

    for kind in kinds:
        _download(kind, cleaned)
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
