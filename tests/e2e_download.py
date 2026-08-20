"""端到端下载验证: 跑 yt-dlp 真实拉一个 19 秒视频.

URL 选 "Me at the zoo" -- YouTube 第一支视频, 短小稳定, jawed 频道.
不走 QThread / service, 直接调 core 层验证 yt-dlp + ffmpeg 路径正确.

输出落 output/e2e_download/.
"""
from __future__ import annotations

from pathlib import Path

import yt_dlp

from app.core.ytdlp_wrapper import DownloadOptions, build_ydl_opts, clean_url
from app.infra.ffmpeg import find_ffmpeg, ffmpeg_dir

TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # Me at the zoo (19s)


def main() -> None:
    print(f"ffmpeg: {find_ffmpeg()}")
    print(f"ffmpeg_dir: {ffmpeg_dir()}")
    if not find_ffmpeg():
        raise SystemExit("ffmpeg not found")

    out_dir = Path("output") / "e2e_download"
    out_dir.mkdir(parents=True, exist_ok=True)
    # 清旧文件
    for p in out_dir.glob("*"):
        if p.is_file():
            p.unlink()

    url, stripped = clean_url(TEST_URL)
    print(f"clean url: {url}  stripped: {stripped}")

    options = DownloadOptions(
        format_kind="mp4",
        quality="720",
        output_dir=out_dir,
        ffmpeg_location=ffmpeg_dir(),
    )

    progress_count = 0

    def hook(d: dict) -> None:
        nonlocal progress_count
        if d.get("status") == "downloading":
            progress_count += 1
            if progress_count % 20 == 0:
                pct = d.get("downloaded_bytes", 0) / max(d.get("total_bytes") or 1, 1) * 100
                print(f"  ... {pct:.0f}%")
        elif d.get("status") == "finished":
            print(f"  finished: {d.get('filename')}")

    opts = build_ydl_opts(options, hook)
    print(f"format spec: {opts['format']}")

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    files = sorted(out_dir.glob("*.mp4"))
    print(f"\nfiles in {out_dir}:")
    for f in files:
        print(f"  {f.name}  ({f.stat().st_size / 1024:.1f} KB)")

    assert files, "no .mp4 in output dir"
    assert files[0].stat().st_size > 100 * 1024, "file too small (<100KB)"
    print("\nOK")


if __name__ == "__main__":
    main()
