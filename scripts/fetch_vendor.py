"""把打包需要的三个外部可执行文件拉到 vendor/ 下.

    python scripts/fetch_vendor.py          # 缺什么补什么
    python scripts/fetch_vendor.py --force  # 全部重新下载
    python scripts/fetch_vendor.py --dest D:\\tmp\\vendor   # 下到别处 (试跑用)

## 为什么要有这个脚本

vendor/ 是 gitignore 的 —— 三个二进制加起来 200MB+, 入库会让仓库永久背着它们,
而且 GitHub 单文件 100MB 是硬上限 (ffmpeg 97MB 已经贴边); 它们还分平台, 提交进去
就是翻倍。代价是**全新 clone 的机器直接打包会失败** (spec 断言中止), MacBook 上就
撞上了这个。有了这个脚本, 新机器一条命令就能补齐。

## 三个文件各干什么

| 文件 | 作用 | 缺了会怎样 |
|---|---|---|
| yt-dlp | 下载引擎本体 | 什么都下不了 |
| ffmpeg | 合并音视频流 / 转 MP3 | 1080p 这类分离流下不了 |
| deno   | 算 YouTube 的 nsig 签名挑战 | **下载报 HTTP 403** |

**ffmpeg 必须是静态构建** —— spec 把 vendor 当 datas 原样拷贝, 不会跟着收依赖库。
mac 上 Homebrew 那个 ffmpeg 只有 441KB, 解码器都在外部 dylib 里, 打出来的包在自己
机器上测什么都正常, 发给没装 Homebrew 的人就"合并失败"。所以这里取的是
ffmpeg-static 的构建, 不是 brew 的。

只用标准库, 不依赖项目环境, 单独跑也行。
"""
from __future__ import annotations

import argparse
import io
import platform
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_UA = {"User-Agent": "video-downloader-fetch-vendor"}


def _is_arm_mac() -> bool:
    return sys.platform == "darwin" and platform.machine() in ("arm64", "aarch64")


# 每项: (子目录, 目标文件名, 下载地址, zip 内的成员名 —— None 表示直接就是可执行文件)
def _targets() -> list[tuple[str, str, str, str | None]]:
    if sys.platform == "win32":
        return [
            (
                "ytdlp", "yt-dlp.exe",
                "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
                None,
            ),
            (
                "ffmpeg", "ffmpeg.exe",
                "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
                "*/bin/ffmpeg.exe",
            ),
            (
                "deno", "deno.exe",
                "https://github.com/denoland/deno/releases/latest/download/"
                "deno-x86_64-pc-windows-msvc.zip",
                "deno.exe",
            ),
        ]
    if sys.platform == "darwin":
        arch = "aarch64-apple-darwin" if _is_arm_mac() else "x86_64-apple-darwin"
        # ffmpeg-static 的资产名用 arm64 / x64
        ff_arch = "arm64" if _is_arm_mac() else "x64"
        return [
            (
                "ytdlp", "yt-dlp",
                "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos",
                None,
            ),
            (
                "ffmpeg", "ffmpeg",
                "https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/"
                f"ffmpeg-darwin-{ff_arch}",
                None,
            ),
            (
                "deno", "deno",
                f"https://github.com/denoland/deno/releases/latest/download/deno-{arch}.zip",
                "deno",
            ),
        ]
    raise SystemExit(f"暂不支持这个平台: {sys.platform} (照着 _targets() 加一档即可)")


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310 (固定的官方地址)
        return resp.read()


def _extract(blob: bytes, member_pattern: str) -> bytes:
    """从 zip 里取出目标成员. 支持 '*/bin/ffmpeg.exe' 这种带通配的路径.

    ffmpeg 的官方压缩包里带版本号目录 (ffmpeg-7.1-essentials_build/bin/ffmpeg.exe),
    版本一换路径就变, 所以按后缀匹配而不是写死全名。
    """
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        if "*" in member_pattern:
            suffix = member_pattern.lstrip("*")
            names = [n for n in zf.namelist() if n.endswith(suffix)]
            if not names:
                raise SystemExit(f"压缩包里找不到 {member_pattern}")
            member = names[0]
        else:
            member = member_pattern
        return zf.read(member)


def fetch(dest_root: Path, force: bool = False) -> int:
    """把缺的文件补齐. 返回实际下载的个数."""
    downloaded = 0
    for subdir, filename, url, member in _targets():
        target = dest_root / subdir / filename
        if target.is_file() and not force:
            size = target.stat().st_size / 1024 / 1024
            print(f"  ✓ 已存在  {subdir}/{filename}  ({size:.0f} MB)")
            continue

        print(f"  ↓ 下载中  {subdir}/{filename} …", flush=True)
        blob = _download(url)
        if member:
            blob = _extract(blob, member)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        if sys.platform != "win32":
            target.chmod(0o755)   # mac/Linux 下下来是没有执行位的
        print(f"    完成    {len(blob)/1024/1024:.0f} MB → {target}")
        downloaded += 1
    return downloaded


def main() -> int:
    parser = argparse.ArgumentParser(description="下载打包所需的 vendor 二进制")
    parser.add_argument("--force", action="store_true", help="已存在也重新下载")
    parser.add_argument("--dest", type=Path, default=_PROJECT_ROOT / "vendor",
                        help="下载到哪个目录 (默认项目的 vendor/)")
    args = parser.parse_args()

    print(f"平台: {sys.platform} / {platform.machine()}")
    print(f"目标: {args.dest}\n")
    count = fetch(args.dest, force=args.force)
    print(f"\n完成, 本次下载 {count} 个文件。")

    if sys.platform == "darwin":
        print(
            "\n提示: mac 上这些文件带了隔离属性, 第一次跑可能被 Gatekeeper 拦。\n"
            f"  xattr -dr com.apple.quarantine {args.dest}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
