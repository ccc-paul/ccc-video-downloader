# 视频下载器

把 YouTube 视频存成本地 MP4 或 MP3 的小工具。

## 给使用者

安装包都在 [Releases](https://github.com/ccc-paul/ccc-video-downloader/releases/latest)，
两个平台各取各的 —— `.exe` 是 Windows 程序，**在 Mac 上装不了也解压不了**。

### Windows

1. 下最新的 `VideoDownloader-Setup-*.exe`，双击安装（**不需要管理员权限**）
2. 打开程序，把 YouTube 链接粘进去
3. 选画质和保存位置，点「加入下载队列」

### macOS（Apple Silicon）

1. 下 `VideoDownloader-1.0.0-macOS-arm64.zip`，双击解压
2. 把 `视频下载器.app` 拖进「应用程序」——
   **别留在「下载」文件夹里直接跑**，macOS 会把它挪到一个随机只读临时目录执行
3. 打开「终端」（聚焦搜索 `Terminal`），粘这一行回车，只需做这一次：

   ```bash
   xattr -dr com.apple.quarantine /Applications/视频下载器.app
   ```

4. 之后双击就能开

> **为什么要第 3 步**：这个包没有 Apple 签名和公证，直接双击会被 Gatekeeper 拦下 ——
> 弹窗写「Apple 无法验证"视频下载器"是否包含恶意软件」，只给 **Move to Trash / Done**
> 两个按钮。点 **Done**，**别点 Move to Trash**。
>
> ⚠️ **macOS 15 起「右键 → 打开」这条老路已经失效了**，网上大部分教程还停在那儿，别试。
>
> 不想用终端的话还有一条路：先双击一次让它被拒（点 Done），然后「系统设置」→
> 「隐私与安全性」→ 往下滚到「安全性」，会多出一行「已阻止使用"视频下载器"…」→
> 点「仍要打开」→ Touch ID / 密码 → 再双击一次。这个按钮只在**失败尝试之后**才出现。
>
> 想让同事双击直接就能开，唯一的正规解法是加入 Apple Developer Program
> （99 美元/年）做签名 + 公证 —— 目前**没买**，所以上面这一步省不掉。
>
> **只支持 Apple Silicon（M1 及以后）**。Intel Mac 打不开，得在 Intel 机器上自行构建，
> 见 [在 Mac 上构建](#在-mac-上构建)。

一次最多同时下 2 个，其余排队。选项会记住，下次打开还是上次那套。

**常见问题**

| 现象 | 处理 |
|---|---|
| 某一条显示「❌ 失败」 | 点那行的 **⟳** 重试。YouTube 偶尔会拒绝某个链接，重试一般就好 |
| 一直失败 | 把日志发给 IT，取当天那个文件：Windows 在 `%APPDATA%\VideoDownloader\logs\`，mac 在 `~/Library/Application Support/VideoDownloader/logs/` |
| 找不到下载的文件 | 点那行的 **📂** 会直接在文件夹里选中它 |
| 粘的是播放列表链接 | 程序会自动只下当前这一个视频，不会把整个列表拖下来 |

下载的文件默认放在「视频」文件夹（mac 上是「影片」/`~/Movies`），可以改。点路径框右边的
**📂** 能直接在文件管理器里打开这个文件夹。

**文件名**默认是「视频标题 - 频道名」，标题截 60 字、频道截 20 字（不截的话经常上百字符，
在文件管理器里根本看不全）。想自己起名就在「文件名」里填一个 —— 留空就还是默认那套。
同名文件已存在时会自动补 `(2)`，不会把上一个覆盖掉，也不会悄悄跳过不下。

---

## 给开发者

PyQt6 桌面应用，把 `yt-dlp` 包装成带队列的图形界面。

四层结构：`ui`（界面）→ `services`（队列编排 + 起 yt-dlp 子进程，QThread）→
`core`（命令行参数组装 + 输出解析，不依赖 PyQt，可独立测试）→
`infra`（配置 / 日志 / SQLite / 外部可执行文件解析）。

> **yt-dlp 是外挂二进制，不是 Python 依赖。** 打包后 Python 库会被编译进 exe 里，
> 既不能 pip 升级、外部副本也抢不过 `FrozenImporter`，等于冻死在打包那一刻 ——
> 而 YouTube 每隔几周换播放器，旧版立刻全线 403。所以改成
> `vendor/ytdlp/yt-dlp.exe` + 子进程调用，启动时复制到 `%APPDATA%` 下再自更新。
> 细节见 [CLAUDE.md](CLAUDE.md)。

### 跑起来

全新 clone 之后**先补 vendor 二进制**，否则打包会中止、下载也用不了：

```powershell
python scripts\fetch_vendor.py       # 三个文件, 约 210MB, 已存在的会跳过
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

mac 上把后两行换成 `pip install -r requirements.txt` 和 `python main.py`，
脚本本身跨平台，会自动取对应平台/架构的资产。

**为什么要自备**：`vendor/` 是 gitignore 的 —— 三个二进制加起来 200MB+，入库会让仓库
永久背着它们，GitHub 单文件 100MB 还是硬上限（ffmpeg 97MB 已经贴边），而且它们分平台，
提交进去就是翻倍。

**三个必须自备的二进制**：

| 放哪 | 干什么 | 缺了会怎样 |
|---|---|---|
| `vendor/ytdlp/yt-dlp`（Windows 是 `yt-dlp.exe`） | 下载引擎本体 | 什么都下不了 |
| `vendor/ffmpeg/ffmpeg`（Windows 是 `ffmpeg.exe`） | 合并音视频流 | 1080p 这类分离流下不了 |
| `vendor/deno/deno`（Windows 是 `deno.exe`） | 算 YouTube 的 nsig 签名挑战 | **下载报 HTTP 403** |

其中 yt-dlp 只是**基线版本** —— 程序启动后会复制到用户目录并自更新，所以随包这份
不必总是最新。

**手工准备的话注意别下错 yt-dlp**（用上面的脚本就不必操心，它取的是对的那个）：

| 平台 | 下这个资产 | 放成 |
|---|---|---|
| Windows | `yt-dlp.exe`（17MB） | `vendor/ytdlp/yt-dlp.exe` |
| macOS | `yt-dlp_macos`（35MB） | `vendor/ytdlp/yt-dlp` ← **要改名**，还要 `chmod +x` |

> ⚠️ **release 里那个名字刚好叫 `yt-dlp` 的（3MB）不能用** —— 它是
> `#!/usr/bin/env python3` 脚本，要目标机器自己装了 Python 才跑得起来。
> 这个坑在 mac 上几乎必踩：文件名天然就对、不用改名，**开发机上还能正常输出版本号**
> （因为开发机有 python3），一路顺畅到装进没装 Python 的同事电脑上才发现废了。
> Windows 反而不会中招 —— 那边要的是 `yt-dlp.exe`，名字对不上。
> spec 打包前会检查文件开头是不是 `#!`，下错了当场拦下。

**ffmpeg 必须取静态构建**（脚本已经处理好了）。mac 上别图省事拿 `brew` 那个：
它只有 441KB，解码器都在外部 dylib 里，打出来的包在自己机器上测什么都正常，
发给没装 Homebrew 的人就「合并失败」。

程序会先找 `vendor/`，找不到再回落系统 PATH 上的同名程序。开发期用 PATH 上的也无所谓；
**要打包发给别人就必须是 `vendor/` 里的静态二进制**。

### 打包（Windows）

```powershell
pyinstaller VideoDownloader.spec
iscc installer.iss
```

spec 会在开打前断言 vendor 里的 yt-dlp / ffmpeg / deno 三个都在，并按当前平台
把「该下哪个资产」一起打进报错信息里 —— 缺了当场报错，而不是等装到同事电脑上才发现。

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

### 在 Mac 上构建

**代码本身是跨平台的**（数据目录、文件管理器调用、可执行文件名都按平台分支），
但 **PyInstaller 既不能交叉编译、也不能跨架构** —— Windows 上打出来的只有 Windows 版；
在 Apple Silicon 上打出来的是 arm64-only，Intel Mac 跑不了
（`file dist/视频下载器.app/Contents/MacOS/VideoDownloader` 可以确认）。

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

mkdir -p vendor/ytdlp vendor/ffmpeg vendor/deno

# yt-dlp: 要 yt-dlp_macos (Mach-O), **不是**那个同名的 3MB python 脚本; 落地改名成 yt-dlp
curl -L -o vendor/ytdlp/yt-dlp \
  https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos
chmod +x vendor/ytdlp/yt-dlp

# ffmpeg 取静态构建, 不要用 Homebrew 的 —— 原因见下面那条坑
curl -L -o vendor/ffmpeg/ffmpeg \
  https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/ffmpeg-darwin-arm64
chmod +x vendor/ffmpeg/ffmpeg

brew install deno && cp "$(which deno)" vendor/deno/

python main.py                     # 先从源码跑一遍确认没问题
pyinstaller VideoDownloader.spec   # 产出 dist/视频下载器.app
```

> **坑：Homebrew 的 ffmpeg 拷进 vendor/ 会打出一个在别人机器上坏掉的包。**
> `brew` 装的 `/opt/homebrew/bin/ffmpeg` 只有 441 KB，真正的解码器全在
> `/opt/homebrew/Cellar/ffmpeg/*/lib/*.dylib` 里。spec 把 vendor 当 `datas` 原样拷贝，
> **不会**跟着收这些 dylib —— 于是自己机器上（装了 Homebrew）测什么都正常，
> 发给同事就是「合并失败」。
> 用 `otool -L vendor/ffmpeg/ffmpeg` 检查：只出现 `/usr/lib/...` 和 `/System/...`
> 才算干净。deno 没这个问题。

**分发**：`installer.iss` 是 Inno Setup 脚本，**Windows 专用**；Mac 侧把 `.app` 压成
zip 发出去就行。

```bash
cd dist
ditto -c -k --sequesterRsrc --keepParent "视频下载器.app" "VideoDownloader-1.0.0-macOS-arm64.zip"
```

用 `ditto` 而不是 `zip`：bundle 里全是符号链接（`Contents/Frameworks/app -> ../Resources/app`
之类），`zip` 会把它们展开成实体副本，包白白大一截。
另外传 GitHub Releases 时**文件名用 ASCII** —— 带中文的资产名会被 GitHub 把中文字符
直接吃掉，变成 `-1.0.0-macOS-arm64.zip`。

**Gatekeeper**：没有 Apple 开发者签名和公证的话，别人下载后双击一定被拦。
PyInstaller 会给 bundle 打一个 ad-hoc 签名（`codesign --verify --deep --strict` 能过），
但 ad-hoc 对 Gatekeeper 不算数 —— `spctl -a -vv` 照样 `rejected`。

**别再写「右键 → 打开」了** —— macOS 15 起苹果**取消了这条绕过路径**：现在弹的是
「Apple 无法验证…」，只有 Move to Trash / Done 两个按钮，右键菜单里的「打开」不再有
豁免效果（2026-08-20 在 macOS 26.5 上确认）。现在能用的只有两条：

```bash
xattr -dr com.apple.quarantine /Applications/视频下载器.app   # 推荐, 复制粘贴一行
```

或者让对方双击被拒后去「系统设置」→「隐私与安全性」→「安全性」里点「仍要打开」
（那个按钮只在失败尝试之后才出现）。

这比 Windows 的 SmartScreen 严格得多。正规解法是加入 Apple Developer Program
（99 美元/年）做签名 + 公证 —— **目前没买**，交付时必须把上面那行命令一起发给对方。

**实测产物**（2026-08-20，macOS 26.5 / Apple Silicon / Python 3.14）：

| 项 | 大小 |
|---|---|
| `dist/视频下载器.app` | 286 MB |
| `VideoDownloader-1.0.0-macOS-arm64.zip` | **105 MB** |

其中 deno 163 MB + ffmpeg 45 MB 占了大头。

验证过：67 个单测 + UI 冒烟 + 720p 分离流合并 + MP3 提取全过；冻结后的 `.app` 启动正常
（日志里 `frozen=True`，ffmpeg / deno 都解析到 `Contents/Resources/vendor/...`）；
解压到全新目录照样能跑；打上 quarantine 属性后 `spctl` 如期 rejected，
`xattr -dr` 清掉后正常。

### Windows 实测产物

（2026-08-20 首次真打）

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
.\.venv\Scripts\python.exe -m tests.e2e_download    # 真实下载 (mp4 + mp3 各一趟)
```

mac 上换成 `.venv/bin/python`，其余一样。
