# CLAUDE.md

本文件给 Claude Code 提供本仓库的工作指引。

## 定位

一个给非技术同事用的桌面小工具：粘 URL → 选画质 → 下载。**没有设置页、没有帮助页、
没有导航菜单** —— 整个程序就一个界面。

用户拿到的是 Inno Setup 打的 exe 安装包，不需要装 Python。

## 常用命令

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.\.venv\Scripts\python.exe main.py                  # 跑起来
.\.venv\Scripts\python.exe -m pytest tests\ -q      # 单测
.\.venv\Scripts\python.exe -m tests.smoke           # UI 冒烟
pyinstaller VideoDownloader.spec && iscc installer.iss   # 打包
```

## 架构

四层，与主线同构，只是每层都薄了很多：

```
ui/main_window.py            单页窗口, 无菜单; 状态栏报 ffmpeg / JS 运行时
ui/pages/downloader_page.py  URL 输入 + 选项 + 队列
        ↓ pyqtSignal
services/download_service.py 队列编排, MAX_CONCURRENT = 2, 每 job 一个 QThread
        ↓
core/ytdlp_wrapper.py        yt-dlp 选项组装 (不依赖 PyQt, 可独立测试)
        ↓
infra/  config / local_db / logger / i18n / ffmpeg / jsruntime / desktop
```

`app/core/` 不准 import `PyQt6.*`。长任务一律在 QThread 里跑，进度用 `pyqtSignal` 回传。

## 关键约定（从主线继承，都是踩过坑的）

**YouTube 下载需要 JS 运行时**（[app/infra/jsruntime.py](app/infra/jsruntime.py)）——
`HTTP Error 403: Forbidden` 的根因：
- YouTube 用 JS 算 nsig/签名挑战。没运行时 yt-dlp 就退回 `android_vr` 客户端，
  直链容易 403、可选清晰度也变少
- 两环缺一不可：① 运行时 `vendor/deno/deno.exe` ② EJS 求解脚本
  （`remote_components=["ejs:github"]`，yt-dlp 自动拉取并缓存）。只有 ① 时日志里会
  出现 `n challenge solving failed`
- 探测不到运行时就**不传** `js_runtimes` key（传空 dict 会把 yt-dlp 默认的 deno 也关掉）
- **`no_warnings` 不许加回去** —— 当初就是它把"没有 JS 运行时"这条关键警告吞掉，
  才让 403 查了半天。yt-dlp 输出走 `_YdlLogger` 进 loguru
- **yt-dlp 要跟紧升级**。升级前先关掉正在运行的应用 —— 它锁着 `yt_dlp/extractor/`，
  uv 会中途失败并把包删残

**vendor 二进制是 gitignore 的**：`ffmpeg.exe` / `deno.exe` 各开发机自备。
`VideoDownloader.spec` 在打包前会断言它们存在，缺了当场报错 —— 不能等装到同事电脑上才发现。
**不打包 `ffprobe.exe`**（96MB，占原包 24%）：实测 MP4 分离流合并和 MP3 提取都不需要它，
yt-dlp 只记一条 warning。若哪天某种格式必须要它，spec 里加回一行即可。

**打包实测数据**（2026-08-20 首次真打）：dist 301MB → 安装包 **89MB** → 安装后 306MB。
验证过：冻结版双击能启动（`frozen=True`）、ffmpeg 和 deno 都解析到 `_MEIPASS\vendor\...`、
静默安装到临时目录后能跑、卸载干净无残留。

> **坑：仓库在 Dropbox 里时 `iscc` 会失败** —— `The output file appears to be in use (32)`，
> 是同步客户端在读那个刚写出的大文件。用 `iscc /O"$env:TEMP\vd_installer" installer.iss`
> 把产物输出到同步盘外面。

**重试新建 job，不复用旧对象**（[download_service.py](app/services/download_service.py)
`retry_job`）：旧 job 的线程亲和性还指着已结束并 `deleteLater` 掉的 QThread，
再 `moveToThread` 会报 "Current thread is not the object's thread" 甚至崩。
UI 行 `rebind` 到新 job 时必须先断开旧 job 的信号。

**QSS 子控件必须写全**（[styles.qss](app/ui/resources/styles.qss)）：样式表一旦命中某控件，
Qt 就从原生绘制切到样式表绘制，**没定义的子控件会退化成残缺画法** —— checkbox 勾选态只剩
一个光秃秃的 ✓ 没方框、combobox 没有下拉箭头。图标走 `{RES}` 占位符
（`main_window._apply_stylesheet` 换成绝对路径）—— QSS 里的相对 `url()` 按进程工作目录
解析，打包后必失效；新增图标记得同步进 `.spec` 的 datas。

**i18n**：UI 字符串一律走 `t("key")`，禁止硬编码。新增时中英两张表都要加。

**没有设置页**，用户选的东西靠 [config.py](app/infra/config.py)
`remember_download_options()` 记住，下次启动 `_restore_options()` 恢复。
配置损坏/画质选项失效都要能回落默认 —— 这是给非技术同事用的，不能开不了。

**应用数据**：`%APPDATA%\VideoDownloader\`（`APP_FOLDER` 常量）。与主线的
`CCCLiveStudio` 分开，两个程序可在同一台机器并存。

## 不要做的事

- 不要把本分支合回 `main`
- 不要把主线那些模块（直播准备 / 链接同步 / PPT 生成 / ATEM / 语音转文字）加回来 ——
  要用那些功能就去用主线
- 不要引入新的重依赖：现在整个依赖就 PyQt6 + yt-dlp + loguru，
  安装包才百来 MB，这是这个工具能发给同事的前提
