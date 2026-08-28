"""视频下载 (设计文档 §4.4)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.ytdlp_wrapper import (
    MAX_FILENAME_STEM,
    DownloadOptions,
    filename_template_for,
    sanitize_stem,
    strip_ansi,
    unique_stem,
)
from app.infra.config import (
    default_download_dir,
    load_config,
    remember_download_options,
)
from app.infra.desktop import open_in_file_manager, reveal_in_file_manager
from app.infra.ffmpeg import is_available as ffmpeg_available
from app.infra.i18n import t
from app.infra.logger import get_logger
from app.services.download_service import DownloadJob, DownloadService, JobStatus
from app.ui.widgets.icon_label import icon_button, set_icon_status

_VIDEO_QUALITIES = [("720", "720p"), ("1080", "1080p"), ("1440", "1440p"), ("best", "Best")]
_AUDIO_QUALITIES = [("128", "128 kbps"), ("192", "192 kbps"), ("320", "320 kbps")]

# 选项行的排版常数 (2026-08-16, 格式/画质/保存到 合并成一行时定).
_GROUP_GAP = 24            # 三组选项之间的留白, 免得挤成一团看不出分组
_QUALITY_WIDTH_SCALE = 1.2  # 画质下拉框: 自然宽度 +20%
_OUTPUT_WIDTH_SCALE = 2.0   # 保存到输入框: 自然宽度 ×2


class DownloaderPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._log = get_logger("ui")
        self._service = DownloadService()
        self._service.job_added.connect(self._add_job_row)
        self._build_ui()
        self._restore_options()

    def shutdown(self) -> None:
        """应用关闭时收尾: 取消下载并 wait 线程."""
        self._service.shutdown()

    # ---------- UI 构建 ----------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)

        title = QLabel(t("page.downloader.title"))
        title.setObjectName("pageTitle")
        root.addWidget(title)
        subtitle = QLabel(t("page.downloader.subtitle"))
        subtitle.setObjectName("pageHint")
        root.addWidget(subtitle)

        root.addLayout(self._build_url_row())
        root.addLayout(self._build_filename_row())

        self._strip_label = QLabel("")
        self._strip_label.setObjectName("pageHint")
        self._strip_label.setVisible(False)
        root.addWidget(self._strip_label)

        root.addLayout(self._build_options_row())

        self._add_btn = QPushButton(t("downloader.add"))
        self._add_btn.setObjectName("primaryButton")
        self._add_btn.setMinimumHeight(34)
        self._add_btn.clicked.connect(self._on_add)
        root.addWidget(self._add_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        queue_title = QLabel(t("downloader.queue.label"))
        queue_title.setStyleSheet("font-size: 17px; font-weight: 600;")
        root.addWidget(queue_title)

        # 队列滚动区
        self._queue_container = QWidget()
        self._queue_layout = QVBoxLayout(self._queue_container)
        self._queue_layout.setContentsMargins(0, 0, 0, 0)
        self._queue_layout.setSpacing(6)
        self._queue_empty_label = QLabel(t("downloader.queue.empty"))
        self._queue_empty_label.setObjectName("pageHint")
        self._queue_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._queue_layout.addWidget(self._queue_empty_label)
        self._queue_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(self._queue_container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll, stretch=1)

    def _build_url_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(t("downloader.url.label")))
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText(t("downloader.url.placeholder"))
        row.addWidget(self._url_input, stretch=1)
        paste = QPushButton(t("downloader.url.paste"))
        paste.clicked.connect(self._on_paste)
        row.addWidget(paste)
        return row

    def _build_filename_row(self) -> QHBoxLayout:
        """自定义输出文件名 (可选).

        默认模板是 "标题 - 频道.ext", YouTube 的标题动辄上百字符, 拼出来的名字长到
        在访达里根本看不全 (2026-08-27 反馈)。留空就还是老样子。
        """
        row = QHBoxLayout()
        row.addWidget(QLabel(t("downloader.filename.label")))
        self._filename_input = QLineEdit()
        self._filename_input.setPlaceholderText(t("downloader.filename.placeholder"))
        self._filename_input.setMaxLength(MAX_FILENAME_STEM)
        # 回车等于点「加入下载队列」—— 手已经在键盘上了
        self._filename_input.returnPressed.connect(self._on_add)
        row.addWidget(self._filename_input, stretch=1)
        return row

    def _build_options_row(self) -> QHBoxLayout:
        """格式 / 画质 / 保存到 挤在同一行 (2026-08-16 按用户要求从三行 QFormLayout 改来).

        原来是 QFormLayout 三行, 画质与音质靠 setRowVisible 互斥切换; 改单行后没有"行"
        可隐藏了, 改成切换两个下拉框自身的可见性 + 复用同一个标签换文字。
        """
        row = QHBoxLayout()
        row.setSpacing(8)

        # 格式 radio
        self._radio_mp4 = QRadioButton(t("downloader.format.mp4"))
        self._radio_mp3 = QRadioButton(t("downloader.format.mp3"))
        self._radio_mp4.setChecked(True)
        self._format_group = QButtonGroup(self)
        self._format_group.addButton(self._radio_mp4)
        self._format_group.addButton(self._radio_mp3)
        self._radio_mp4.toggled.connect(self._on_format_changed)
        row.addWidget(QLabel(t("downloader.format.label")))
        row.addWidget(self._radio_mp4)
        row.addWidget(self._radio_mp3)

        row.addSpacing(_GROUP_GAP)

        # 画质 (mp4) / 音质 (mp3) -- 同位置互斥显示, 标签文字跟着换
        self._quality_label = QLabel(t("downloader.quality.video"))
        row.addWidget(self._quality_label)

        self._video_quality = QComboBox()
        for v, label in _VIDEO_QUALITIES:
            self._video_quality.addItem(label, userData=v)
        self._audio_quality = QComboBox()
        for v, label in _AUDIO_QUALITIES:
            self._audio_quality.addItem(label, userData=v)
        # 比自然宽度再宽 20% —— 下拉框贴着文字太局促
        for combo in (self._video_quality, self._audio_quality):
            combo.setMinimumWidth(int(combo.sizeHint().width() * _QUALITY_WIDTH_SCALE))
            row.addWidget(combo)

        self._update_quality_visibility()

        row.addSpacing(_GROUP_GAP)

        # 输出目录: 首次是系统「视频」文件夹, 之后记住上次选的 (见 _restore_options)
        row.addWidget(QLabel(t("downloader.output.dir")))
        self._output_dir = QLineEdit()
        # 路径通常很长, 给 2 倍自然宽度; stretch=1 让它继续吃掉本行剩余空间
        self._output_dir.setMinimumWidth(int(self._output_dir.sizeHint().width() * _OUTPUT_WIDTH_SCALE))
        row.addWidget(self._output_dir, stretch=1)
        browse = QPushButton(t("common.browse"))
        browse.clicked.connect(self._on_browse_dir)
        row.addWidget(browse)
        # 「浏览...」是**选目录**, 弹的是选择框; 想直接去文件管理器看看下好的东西,
        # 得另给一个入口 —— 否则用户只能点浏览, 然后对着一个文件全灰的选择框发愣
        # (2026-08-24 反馈)。
        self._open_dir_btn = QPushButton(t("common.open.dir"))
        self._open_dir_btn.clicked.connect(self._on_open_dir)
        row.addWidget(self._open_dir_btn)

        return row

    # ---------- 选项记忆 ----------

    def _restore_options(self) -> None:
        """恢复上次用的选项 —— 本工具没有设置页, 就靠这个免去每次重填.

        配置里的值不合法 (画质选项改过、目录被删) 时回落默认, 不让程序卡住。
        """
        cfg = load_config().get("download") or {}

        saved_dir = str(cfg.get("output_dir") or "").strip()
        self._output_dir.setText(saved_dir or str(default_download_dir()))

        if cfg.get("format_kind") == "mp3":
            self._radio_mp3.setChecked(True)
        else:
            self._radio_mp4.setChecked(True)

        for combo, key, fallback in (
            (self._video_quality, "video_quality", "1080"),
            (self._audio_quality, "audio_quality", "192"),
        ):
            index = combo.findData(cfg.get(key, fallback))
            if index < 0:
                index = max(combo.findData(fallback), 0)
            combo.setCurrentIndex(index)

        self._update_quality_visibility()

    def _remember_options(self) -> None:
        remember_download_options(
            output_dir=self._output_dir.text().strip(),
            format_kind="mp3" if self._radio_mp3.isChecked() else "mp4",
            video_quality=self._video_quality.currentData(),
            audio_quality=self._audio_quality.currentData(),
        )

    # ---------- 事件 ----------

    def _on_format_changed(self) -> None:
        self._update_quality_visibility()

    def _update_quality_visibility(self) -> None:
        is_mp4 = self._radio_mp4.isChecked()
        self._video_quality.setVisible(is_mp4)
        self._audio_quality.setVisible(not is_mp4)
        self._quality_label.setText(
            t("downloader.quality.video") if is_mp4 else t("downloader.quality.audio")
        )

    def _on_paste(self) -> None:
        cb = QGuiApplication.clipboard()
        text = cb.text().strip()
        if text:
            self._url_input.setText(text)

    def _on_open_dir(self) -> None:
        """在系统文件管理器里打开当前的保存目录."""
        raw = self._output_dir.text().strip()
        if not raw:
            QMessageBox.warning(self, t("downloader.error.title"), t("downloader.error.no_dir"))
            return
        target = Path(raw)
        if not target.is_dir():
            # 目录被删了/换了盘符; 别静默什么也不发生, 那看起来像按钮坏了
            QMessageBox.warning(
                self, t("downloader.error.title"),
                t("downloader.error.dir_gone").format(dir=target),
            )
            return
        open_in_file_manager(target)

    def _on_browse_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, t("downloader.output.dir"), self._output_dir.text())
        if d:
            self._output_dir.setText(d)

    def _on_add(self) -> None:
        url = self._url_input.text().strip()
        if not url:
            QMessageBox.warning(self, t("downloader.error.title"), t("downloader.error.no_url"))
            return
        if not ffmpeg_available():
            QMessageBox.critical(self, t("downloader.error.title"), t("downloader.error.no_ffmpeg"))
            return

        raw_dir = self._output_dir.text().strip()
        if not raw_dir:
            QMessageBox.warning(self, t("downloader.error.title"), t("downloader.error.no_dir"))
            return
        output_dir = Path(raw_dir)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            # 同事可能手打一个不存在/没权限的路径; 早点说清楚, 别等下载完才失败
            QMessageBox.critical(
                self, t("downloader.error.title"),
                t("downloader.error.bad_dir").format(dir=raw_dir, err=e),
            )
            return

        if self._radio_mp4.isChecked():
            fmt = "mp4"
            quality = self._video_quality.currentData()
        else:
            fmt = "mp3"
            quality = self._audio_quality.currentData()

        raw_name = self._filename_input.text().strip()
        stem = sanitize_stem(raw_name)
        if raw_name and not stem:
            # 整串都是非法字符 —— 别默默回落到默认名字, 用户会以为自己改了名
            QMessageBox.warning(
                self, t("downloader.error.title"),
                t("downloader.error.bad_filename").format(name=raw_name),
            )
            return
        # 同名文件已存在就补 " (2)": yt-dlp 撞名会跳过下载还报成功,
        # 两个不同视频起同一个名字时第二个会悄悄没下
        stem = unique_stem(output_dir, stem, fmt)

        options = DownloadOptions(
            format_kind=fmt,
            quality=quality,
            output_dir=output_dir,
            filename_template=filename_template_for(stem),
        )

        from app.core.ytdlp_wrapper import clean_url
        cleaned, stripped = clean_url(url)
        if stripped:
            self._strip_label.setText(t("downloader.url.stripped").format(keys=", ".join(stripped)))
            self._strip_label.setVisible(True)
        else:
            self._strip_label.setVisible(False)

        self._service.add_job(cleaned, options)
        self._url_input.clear()
        self._filename_input.clear()
        self._remember_options()  # 下次打开还是这套

    def _add_job_row(self, job: DownloadJob) -> None:
        self._queue_empty_label.setVisible(False)
        row = _JobRowWidget(job)
        row.remove_requested.connect(lambda r=row: self._remove_row(r))
        row.retry_requested.connect(lambda r=row: self._retry_row(r))
        # 插入到顶部 (最新任务在上)
        self._queue_layout.insertWidget(0, row)

    def _retry_row(self, row: "_JobRowWidget") -> None:
        """重试: service 新建一个 job, 本行改盯它 —— 不新增行, 原地重来."""
        new_job = self._service.retry_job(row.job)
        if new_job is None:
            return
        row.rebind(new_job)

    def _remove_row(self, row: "_JobRowWidget") -> None:
        self._queue_layout.removeWidget(row)
        row.deleteLater()
        # 还有没有别的 row?
        has_jobs = any(
            isinstance(self._queue_layout.itemAt(i).widget(), _JobRowWidget)
            for i in range(self._queue_layout.count())
        )
        self._queue_empty_label.setVisible(not has_jobs)


# 标题/链接列的最小宽度: 再窄就只能一行挤两三个字, 还不如让窗口出横向滚动条
_TITLE_MIN_WIDTH = 200
# 信息列 (文件名 · 画质 · 大小 · 时间) 的宽度区间: 够放下常见文件名, 又不至于
# 把标题挤没。文字在这个区间里自己折行。
_INFO_MIN_WIDTH = 240
_INFO_MAX_WIDTH = 320


class _JobRowWidget(QFrame):
    """队列里的单个任务行. 连接到 DownloadJob 的信号."""

    remove_requested = pyqtSignal()
    retry_requested = pyqtSignal()

    def __init__(self, job: DownloadJob) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._job = job

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # 操作列: 取消 / 打开 / 重试 / 移除 (只留图标, 文字进 tooltip)
        self._cancel_btn = _icon_button(t("downloader.job.cancel"), self._on_cancel)
        layout.addWidget(self._cancel_btn)
        self._open_btn = _icon_button(t("downloader.job.open"), self._on_open)
        self._open_btn.setVisible(False)
        layout.addWidget(self._open_btn)
        # 只在失败/取消后出现 —— 间歇性 403 时不必重新粘链接
        self._retry_btn = _icon_button(t("downloader.job.retry"), self.retry_requested.emit)
        self._retry_btn.setVisible(False)
        layout.addWidget(self._retry_btn)
        self._remove_btn = _icon_button(t("downloader.job.remove"), self.remove_requested.emit)
        layout.addWidget(self._remove_btn)

        # 状态只显示图标 (✓ / ❌ / ⏳ …), 文字进 tooltip —— 队列一长, 一列中文
        # 状态词占宽又噪, 图标已经够辨识 (2026-08-16 反馈)
        self._status_label = QLabel()
        self._status_label.setFixedWidth(24)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)
        self._set_status_text(t("downloader.job.status.queued"))

        # 文件名 / 视频链接 分两行同列 (第一行文件名, 第二行灰色链接)
        #
        # **必须 setWordWrap(True) + 横向 Ignored**, 否则长标题会把整行撑爆:
        # 不换行的 QLabel 其 minimumSizeHint 就是整串文字的宽度 (实测那条讚美之泉的
        # 标题要 826px), 布局无法把它压窄, 于是右边的进度条和信息列被顶到窗口外面
        # ——用户看到的就是"按钮跑到界面外了" (2026-08-24 反馈)。
        # Ignored 让 label 不再拿 sizeHint 说话, 有多少宽度用多少, 剩下的往下换行;
        # 再给个下限, 免得被进度条/信息列挤成一条缝。
        self._name_label = QLabel(job.url)
        self._url_label = QLabel(job.url)
        self._url_label.setObjectName("pageHint")
        for label in (self._name_label, self._url_label):
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setMinimumWidth(_TITLE_MIN_WIDTH)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title_col.addWidget(self._name_label)
        title_col.addWidget(self._url_label)
        layout.addLayout(title_col, stretch=1)

        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)  # 千分制更平滑
        self._progress.setValue(0)
        self._progress.setMinimumWidth(120)
        layout.addWidget(self._progress)

        # 下载中显示 速度/ETA; 完成后显示 实际画质 · 文件大小 · 下载时间
        # 装得下文件名, 就必须会换行 —— 否则长文件名把行撑爆, 又变回"进度条被顶出
        # 可视区"那个 bug (见 tests/test_job_row_layout.py)。
        # **这里不能用 Ignored**: 标题列是 stretch=1, 而 Ignored 会让本列的 sizeHint
        # 被无视, 空间全被标题吃掉, 本列再按 minimumWidth 摆出去就超出行宽了。
        # 改成限定宽度区间: 文字在 240~320 之间自己折行, 不参与抢空间。
        self._info_label = QLabel("")
        self._info_label.setWordWrap(True)
        self._info_label.setMinimumWidth(_INFO_MIN_WIDTH)
        self._info_label.setMaximumWidth(_INFO_MAX_WIDTH)
        layout.addWidget(self._info_label)

        self._connect_job(job)

    @property
    def job(self) -> DownloadJob:
        return self._job

    # ---------- job 绑定 ----------

    def _connect_job(self, job: DownloadJob) -> None:
        job.progress.connect(self._on_progress)
        job.status_changed.connect(self._on_status_changed)
        job.finished.connect(self._on_finished)

    def rebind(self, job: DownloadJob) -> None:
        """重试后本行改盯新的 job —— 不新增一行, 原地从头再来.

        必须先断开旧 job 的信号: 旧对象还活着 (在 service 的 _jobs 里留着做记录),
        不断开的话它若再发信号会把本行的显示改乱。
        """
        for signal, slot in (
            (self._job.progress, self._on_progress),
            (self._job.status_changed, self._on_status_changed),
            (self._job.finished, self._on_finished),
        ):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass  # 已断开; 幂等即可

        self._job = job
        self._connect_job(job)

        # UI 复位
        self._progress.setValue(0)
        self._info_label.setText("")
        self._set_status_text(t("downloader.job.status.queued"))
        self._cancel_btn.setVisible(True)
        self._retry_btn.setVisible(False)
        self._open_btn.setVisible(False)

    def _set_status_text(self, label: str) -> None:
        set_icon_status(self._status_label, label)

    def _on_progress(self, percent: float, speed: str, eta: str) -> None:
        self._progress.setValue(int(percent * 1000))
        info_parts: list[str] = []
        if speed:
            info_parts.append(speed)
        if eta:
            info_parts.append(f"ETA {eta}")
        self._info_label.setText("  ".join(info_parts))

    def _on_status_changed(self, status: str) -> None:
        # info_fetched 是特殊事件: 此时 job.title 已可用
        if status == "info_fetched":
            if self._job.title:
                self._name_label.setText(self._job.title)
            return
        # retrying 同样不属于 JobStatus: 这次失败了, 正在换新链接重来
        if status == "retrying":
            self._info_label.setText(
                t("downloader.job.retrying").format(
                    n=self._job.attempt + 1, total=self._job.max_attempts
                )
            )
            return
        try:
            js = JobStatus(status)
        except ValueError:
            return
        self._set_status_text(t(f"downloader.job.status.{js.value}"))

    def _on_finished(self, ok: bool, detail: str) -> None:
        self._cancel_btn.setVisible(False)
        if ok and self._job.output_path:
            # 第一行保持视频标题 (自定义文件名时, 标题和文件名可能完全对不上, 两个都要
            # 看得见); 文件名进 info 列, 排在 画质 · 大小 · 时间 前面 (2026-08-27)
            self._open_btn.setVisible(True)
            self._info_label.setText(self._completed_meta())
            # 兜底置满: 正常路径靠 yt-dlp 的 finished hook 推到 100%, 但合并/转码
            # 收尾的那几步不再回调, 进度条可能停在 99% 上
            self._progress.setValue(self._progress.maximum())
            return
        # 失败或被取消: 给个重试入口, 免得用户重新粘一遍链接
        self._retry_btn.setVisible(True)
        if detail not in ("cancelled",):
            # 把错误塞 info_label, 方便目测. strip_ansi: yt-dlp 报错自带终端颜色码,
            # 不洗掉会在 Qt 标签里显示成一串乱码方块.
            self._info_label.setText(strip_ansi(detail)[:60])

    def _completed_meta(self) -> str:
        """完成后在 info 区显示: 文件名 · 实际画质 · 文件大小 · 下载时间 (跳过取不到的项)."""
        parts: list[str] = []
        if self._job.output_path:
            parts.append(self._job.output_path.name)
        if self._job.actual_quality:
            parts.append(self._job.actual_quality)
        size = _file_size(self._job.output_path)
        if size:
            parts.append(size)
        parts.append(datetime.now().strftime("%H:%M:%S"))
        return "  ·  ".join(parts)

    def _on_cancel(self) -> None:
        self._job.cancel()

    def _on_open(self) -> None:
        """在文件管理器里**选中**下好的文件, 而不是只打开它所在的文件夹.

        README 一直是这么承诺的 ("点那行的 📂 会直接在文件夹里选中它"), 但之前调的是
        open_in_file_manager —— 文件夹一多, 用户还得自己在里面找。reveal 早就写好了
        (mac `open -R` / Windows `explorer /select`), 只是没被接上 (2026-08-24)。
        文件不存在时 reveal 会自动回落到打开父目录。
        """
        if not self._job.output_path:
            return
        reveal_in_file_manager(self._job.output_path)


# 共用实现在 widgets/icon_label.py; 这里保留同名薄封装, 免得改动本页各处调用点
_icon_button = icon_button


def _file_size(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return _human_size(path.stat().st_size)
    except OSError:
        return ""


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
