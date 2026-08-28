# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本 —— 视频下载器 (单功能版).

与主线 CCCLiveStudio.spec 的差别: 依赖砍到只剩 PyQt6 + yt-dlp + loguru,
所以没有 keyring/pywin32/pyodbc/google/faster-whisper/CUDA 那一大堆
hiddenimports 和 collect_all, 体积从 ~1GB 降到百来 MB。

关键点:
- vendor 里的三个可执行文件**必须打进去**, 否则同事那边一用就出事:
    yt-dlp  缺了 → 下载引擎本体没了, 什么都下不了
    ffmpeg  缺了 → 1080p 这类分离流无法合并音视频
    deno    缺了 → YouTube 签名挑战算不出来, 直接 HTTP 403
  三个都按项目相对结构放进 _MEIPASS, 让 ytdlp_bin.py / ffmpeg.py / jsruntime.py
  里 Path(__file__).parent... 的定位逻辑在冻结后依然成立 (无需改代码)。
- QSS 引用的图标要一起带上, 否则 checkbox 没方框、下拉框没箭头。

调试期把 CONSOLE 设 True 能看到导入错误; 交付时设 False。
"""
import re
import sys
from pathlib import Path

CONSOLE = False  # True=带控制台便于排错; False=无控制台正式交付

_VENDOR = Path(SPECPATH) / "vendor"

# 版本号从 app/__init__.py 读, 别再手抄 —— 抄漏了 .app 在访达里就一直报旧版本
# (实测: 1.0.0 之后一直没跟上, 到 1.1.2 才发现 Finder 里还写着 1.0.0)。
_VERSION = re.search(
    r'__version__ = "([^"]+)"',
    (Path(SPECPATH) / "app" / "__init__.py").read_text(encoding="utf-8"),
).group(1)

datas = [
    ("app/ui/resources/styles.qss", "app/ui/resources"),
    # checkbox / radio / 下拉箭头图标; styles.qss 用 {RES} 拼绝对路径引用
    ("app/ui/resources/check.png", "app/ui/resources"),
    ("app/ui/resources/check@2x.png", "app/ui/resources"),
    ("app/ui/resources/radio-dot.png", "app/ui/resources"),
    ("app/ui/resources/radio-dot@2x.png", "app/ui/resources"),
    ("app/ui/resources/chevron.png", "app/ui/resources"),
    ("app/ui/resources/chevron@2x.png", "app/ui/resources"),
    ("app/ui/resources/chevron-disabled.png", "app/ui/resources"),
    ("app/ui/resources/chevron-disabled@2x.png", "app/ui/resources"),
]

# vendor 二进制: 缺哪个都会让用户那边直接用不了, 所以打包前先断言存在,
# 别等装到别人电脑上才发现 (gitignore 掉了, 很容易忘记放)
#
# **不打 ffprobe** (96MB, 占原包 24%): 实测 MP4 分离流合并和 MP3 提取都不需要它,
# yt-dlp 只会记一条 warning。本工具不用嵌入缩略图/元数据那些需要探测媒体的功能。
# 若哪天发现某种格式必须要它, 把 f"ffmpeg/ffprobe{_EXE}" 加回下面这行即可。
#
# 可执行文件名按平台取: Windows 带 .exe, mac/Linux 不带 —— 与
# app/infra/ffmpeg.py、jsruntime.py 的解析逻辑保持一致。
_EXE = ".exe" if sys.platform == "win32" else ""

# 每个文件配一句"从哪儿弄" —— 撞上断言的人多半正是不知道该放什么进去,
# 只报"缺文件"等于让他去猜 (别再笼统说 brew: brew 装不出 yt-dlp 的 standalone)。
_WHERE = {
    "ytdlp": (
        "yt-dlp: https://github.com/yt-dlp/yt-dlp/releases/latest\n"
        + (
            "  取 yt-dlp.exe (17MB), 放成 vendor/ytdlp/yt-dlp.exe"
            if sys.platform == "win32"
            else "  取 **yt-dlp_macos** (35MB, Mach-O), 改名放成 vendor/ytdlp/yt-dlp 并 chmod +x\n"
            "  ⚠️ 别下那个名字刚好叫 `yt-dlp` 的 (3MB): 它是 python3 脚本, "
            "开发机有 Python 跑得通, 装到没 Python 的用户机上直接废"
        )
    ),
    "ffmpeg": (
        "ffmpeg: 必须是**静态构建**\n"
        + (
            "  https://www.gyan.dev/ffmpeg/builds/ 的 essentials 版"
            if sys.platform == "win32"
            else "  https://github.com/eugeneware/ffmpeg-static/releases 的 ffmpeg-darwin-arm64\n"
            "  ⚠️ 别用 `brew install` 那个: 它只有 441KB, 解码器都在 Cellar 的 dylib 里, "
            "打出来的包只在装了 Homebrew 的机器上能用"
        )
    ),
    "deno": (
        "deno: https://github.com/denoland/deno/releases\n"
        + (
            "  取 deno-x86_64-pc-windows-msvc.zip"
            if sys.platform == "win32"
            else "  `brew install deno` 后 cp \"$(which deno)\" vendor/deno/ 即可 (它是静态的)"
        )
    ),
}

for rel in (f"ytdlp/yt-dlp{_EXE}", f"ffmpeg/ffmpeg{_EXE}", f"deno/deno{_EXE}"):
    name = Path(rel).parent.name
    src = _VENDOR / rel
    if not src.is_file():
        raise SystemExit(
            f"打包中止: 缺少 {src}\n"
            f"vendor/ 是 gitignore 的, 各开发机自备。这个文件的来源:\n\n"
            f"{_WHERE[name]}\n"
        )

    # 名字对不代表东西对: yt-dlp 的 release 里那个 3MB 的 `yt-dlp` 是 python3 脚本,
    # 文件名跟 mac/Linux 要的一模一样, 开发机上 `--version` 还照常输出 (因为开发机
    # 有 Python) —— 一路顺畅到装进用户电脑才发现废了。这里当场拦下。
    if sys.platform != "win32":
        with open(src, "rb") as fh:
            if fh.read(2) == b"#!":
                raise SystemExit(
                    f"打包中止: {src} 是脚本不是可执行文件\n"
                    f"(开头是 #!, 多半下成了那个 3MB 的 python3 版)\n\n"
                    f"{_WHERE[name]}\n"
                )

    datas.append((str(src), f"vendor/{Path(rel).parent}"))

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 这些都不再需要了; 显式排除能再省一截体积, 也避免误打进无关依赖
    excludes=[
        "tkinter", "matplotlib", "pytest", "PyQt5", "PySide6", "PySide2",
        "numpy", "PIL", "pandas",
        "keyring", "pyodbc", "win32com", "comtypes", "pythoncom",
        "openai", "googleapiclient", "google_auth_oauthlib",
        "faster_whisper", "ctranslate2", "av", "torch",
        "pptx", "docx",
        # yt-dlp 现在以 vendor/ytdlp/yt-dlp.exe 的形式外挂调用, 不再作为库打进来。
        # 打进来的话就冻死在 exe 里没法更新 —— 那正是 2026-08-21 全线 403 的成因。
        "yt_dlp",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE,
    disable_windowed_traceback=False,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VideoDownloader",
)

# macOS: 再包一层 .app —— 双击 COLLECT 出来的裸可执行文件会弹终端窗口,
# 而且没有图标、不能拖进「应用程序」。BUNDLE 只在 mac 上生效, 别的平台忽略。
#
# ⚠️ PyInstaller **不能跨平台交叉编译**: Windows 上跑这个 spec 只出 Windows 版,
# 要 Mac 版必须在 Mac 上再跑一次。
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="视频下载器.app",
        icon=None,
        bundle_identifier="com.ccc.videodownloader",
        info_plist={
            "CFBundleName": "视频下载器",
            "CFBundleDisplayName": "视频下载器",
            "CFBundleShortVersionString": _VERSION,
            "CFBundleVersion": _VERSION,
            # Retina 下不加这条界面会被放大成糊的
            "NSHighResolutionCapable": True,
        },
    )
