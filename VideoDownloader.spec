# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本 —— 视频下载器 (单功能版).

与主线 CCCLiveStudio.spec 的差别: 依赖砍到只剩 PyQt6 + yt-dlp + loguru,
所以没有 keyring/pywin32/pyodbc/google/faster-whisper/CUDA 那一大堆
hiddenimports 和 collect_all, 体积从 ~1GB 降到百来 MB。

关键点:
- vendor 里的两个可执行文件**必须打进去**, 否则同事那边一用就出事:
    ffmpeg  缺了 → 1080p 这类分离流无法合并音视频
    deno    缺了 → YouTube 签名挑战算不出来, 直接 HTTP 403
  两者都按项目相对结构放进 _MEIPASS, 让 ffmpeg.py / jsruntime.py 里
  Path(__file__).parent... 的定位逻辑在冻结后依然成立 (无需改代码)。
- QSS 引用的图标要一起带上, 否则 checkbox 没方框、下拉框没箭头。

调试期把 CONSOLE 设 True 能看到导入错误; 交付时设 False。
"""
import sys
from pathlib import Path

CONSOLE = False  # True=带控制台便于排错; False=无控制台正式交付

_VENDOR = Path(SPECPATH) / "vendor"

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
for rel in (f"ffmpeg/ffmpeg{_EXE}", f"deno/deno{_EXE}"):
    src = _VENDOR / rel
    if not src.is_file():
        raise SystemExit(
            f"打包中止: 缺少 {src}\n"
            "vendor/ 是 gitignore 的, 请先把 ffmpeg 和 deno 放进去再打包。\n"
            "mac 上可以 `brew install ffmpeg deno` 后把二进制拷进 vendor/, "
            "或直接依赖 PATH (那样就别打包 vendor, 但用户机器上必须装好)。"
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
            "CFBundleShortVersionString": "1.0.0",
            # Retina 下不加这条界面会被放大成糊的
            "NSHighResolutionCapable": True,
        },
    )
