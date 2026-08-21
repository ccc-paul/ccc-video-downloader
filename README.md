# 视频下载器

把 YouTube 视频存成本地 MP4 或 MP3 的小工具。

## 给使用者

安装包都在 [Releases](https://github.com/ccc-paul/ccc-video-downloader/releases/latest)，
两个平台各取各的 —— `.exe` 是 Windows 程序，**在 Mac 上装不了也解压不了**。

### Windows

1. 下 `VideoDownloader-Setup-1.0.0.exe`，双击安装（**不需要管理员权限**）
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

下载的文件默认放在「视频」文件夹（mac 上是「影片」/`~/Movies`），可以改。

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
| `vendor/ffmpeg/ffmpeg`（Windows 是 `ffmpeg.exe`） | 合并音视频流 | 1080p 这类分离流下不了 |
| `vendor/deno/deno`（Windows 是 `deno.exe`） | 算 YouTube 的 nsig 签名挑战 | **下载报 HTTP 403** |

Windows：deno 从 <https://github.com/denoland/deno/releases> 下
`deno-x86_64-pc-windows-msvc.zip`，ffmpeg 用 essentials 版即可（那是静态的）。

macOS：deno 用 `brew install deno` 就行（它本身是静态的，163 MB）。
**ffmpeg 不能用 Homebrew 那个** —— 见 [在 Mac 上构建](#在-mac-上构建) 里的坑，
取静态构建。

程序会先找 `vendor/`，找不到再回落系统 PATH 上的同名程序。开发期只是自己跑一跑，
用 PATH 上的也无所谓；**要打包发给别人就必须是静态二进制**。

### 打包（Windows）

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

### 在 Mac 上构建

**代码本身是跨平台的**（数据目录、文件管理器调用、可执行文件名都按平台分支），
但 **PyInstaller 既不能交叉编译、也不能跨架构** —— Windows 上打出来的只有 Windows 版；
在 Apple Silicon 上打出来的是 arm64-only，Intel Mac 跑不了
（`file dist/视频下载器.app/Contents/MacOS/VideoDownloader` 可以确认）。

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

mkdir -p vendor/ffmpeg vendor/deno
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
.\.venv\Scripts\python.exe -m tests.e2e_download    # 真实下载一个 19s 的视频
```

mac 上换成 `.venv/bin/python`，其余一样。
