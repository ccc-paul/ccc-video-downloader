# 视频下载器

把 YouTube 视频存成本地 MP4 或 MP3 的小工具。

![功能](docs/screenshot.png)

## 给使用者

1. 双击 `VideoDownloader-Setup-1.0.0.exe` 安装（**不需要管理员权限**）
2. 打开程序，把 YouTube 链接粘进去
3. 选画质和保存位置，点「加入下载队列」

一次最多同时下 2 个，其余排队。选项会记住，下次打开还是上次那套。

**常见问题**

| 现象 | 处理 |
|---|---|
| 某一条显示「❌ 失败」 | 点那行的 **⟳** 重试。YouTube 偶尔会拒绝某个链接，重试一般就好 |
| 一直失败 | 把日志发给 IT：`%APPDATA%\VideoDownloader\logs\` 下当天那个文件 |
| 找不到下载的文件 | 点那行的 **📂** 会直接在文件夹里选中它 |
| 粘的是播放列表链接 | 程序会自动只下当前这一个视频，不会把整个列表拖下来 |

下载的文件默认放在「视频」文件夹，可以改。

---

## 给开发者

PyQt6 桌面应用，把 `yt-dlp` 包装成带队列的图形界面。

四层结构：`ui`（界面）→ `services`（队列编排，QThread）→ `core`（yt-dlp 选项组装，
不依赖 PyQt，可独立测试）→ `infra`（配置 / 日志 / SQLite / 外部可执行文件解析）。

### 跑起来

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

**两个必须自备的二进制**（`vendor/` 已 gitignore，各开发机自己放）：

| 放哪 | 干什么 | 缺了会怎样 |
|---|---|---|
| `vendor/ffmpeg/ffmpeg.exe`（还要 `ffprobe.exe`） | 合并音视频流 | 1080p 这类分离流下不了 |
| `vendor/deno/deno.exe` | 算 YouTube 的 nsig 签名挑战 | **下载报 HTTP 403** |

deno 从 <https://github.com/denoland/deno/releases> 下 `deno-x86_64-pc-windows-msvc.zip`，
ffmpeg 用 essentials 版即可。程序也会回落到系统 PATH 上的同名程序。

### 打包

```powershell
pyinstaller VideoDownloader.spec
iscc installer.iss
```

spec 会在开打前断言 vendor 里的 ffmpeg 和 deno 都在 —— 缺了当场报错，
而不是等装到同事电脑上才发现。

**如果仓库放在 Dropbox / OneDrive 里**，`iscc` 会报
`The output file appears to be in use (32)` —— 同步客户端正在读那个刚写出来的
大文件。用 `/O` 把产物输出到同步盘外面即可：

```powershell
iscc /O"$env:TEMP\vd_installer" installer.iss
```

需要 Inno Setup（`winget install JRSoftware.InnoSetup`，装到用户目录，不需要管理员）。
简体中文向导要额外放一份非官方语言包到 `<Inno安装目录>\Languages\ChineseSimplified.isl`
（官方发行版不带），来源见
<https://github.com/kira-96/Inno-Setup-Chinese-Simplified-Translation>。

**实测产物**（2026-08-20）：

| 项 | 大小 |
|---|---|
| PyInstaller 输出 `dist\VideoDownloader\` | 301 MB |
| 安装包 `VideoDownloader-Setup-1.0.0.exe` | **89 MB** |
| 安装后占用 | 306 MB |

其中 ffmpeg (97MB) + deno (93MB) 就占了 190MB，砍不掉 —— 少哪个都会让同事那边直接用不了。

### 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -q      # 单测
.\.venv\Scripts\python.exe -m tests.smoke           # 起窗口 1.5s 自动退出
.\.venv\Scripts\python.exe -m tests.e2e_download <URL>   # 真实下载
```
