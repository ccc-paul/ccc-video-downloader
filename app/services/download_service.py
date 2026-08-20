"""下载服务: QThread 队列, 最多 2 并发, pyqtSignal 回 UI 进度 (设计文档 §4.4).

DownloadService 全局持有一个; UI 的 DownloaderPage 监听 job_added 信号建 UI 行.
"""
from __future__ import annotations

from dataclasses import replace
from enum import Enum
from pathlib import Path
from uuid import uuid4

import yt_dlp
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from app.core import ytdlp_wrapper
from app.core.ytdlp_wrapper import DownloadOptions
from app.infra.ffmpeg import ffmpeg_dir
from app.infra.local_db import connection
from app.infra.logger import get_logger

log = get_logger("download")


class JobStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class _CancelledByUser(Exception):
    """progress_hook 抛这个让 yt-dlp 停掉. 不要 catch 当作真错误."""


# 单个任务的最大尝试次数 (含首次). 2026-08-16 加。
#
# **为什么需要** —— YouTube 会间歇性地给出一批下不动的直链: 提取本身成功, 但拿到的
# googlevideo URL 一请求就 403 Forbidden。实测在开发机上约**一半**的尝试会中招, 且与
# player client / 编码 / 清晰度 / User-Agent / 并发数 / 具体视频**都无关** —— 同一条坏
# URL 换 requests / urllib / curl 三种客户端一样 403, 说明坏的是提取出来的 URL 本身,
# 不是请求方式。根因未查明 (PO Token provider 装上后无显著改善)。
#
# 重试之所以有效, 是因为**每次重试都重新 extract_info 换一批新链接** —— 单纯重发同一条
# URL 没有意义。实测 5 个任务 × 最多 3 次 = 5/5 全成 (共 7 次请求)。
_MAX_ATTEMPTS = 3

# 重试前的等待秒数 (第 1 次失败后等 3s, 第 2 次后等 6s). 拆成小片轮询以便及时响应取消.
_RETRY_BACKOFF_SEC = (3, 6)


def _backoff_for(attempt: int) -> int:
    """第 attempt 次失败后该等几秒. 次数超出表长就沿用最后一档, 免得调大
    _MAX_ATTEMPTS 时越界。"""
    return _RETRY_BACKOFF_SEC[min(attempt, len(_RETRY_BACKOFF_SEC)) - 1]


def _extract_quality(info: dict, format_kind: str) -> str:
    """从 yt-dlp info 里取**实际**下到的画质: mp4=分辨率 (如 1080p), mp3=码率.

    实际值可能和请求的不同 (YouTube 没有该清晰度时会降档), 所以从下载后的 info 取,
    而不是回显用户选的。合并格式 (bestvideo+bestaudio) 顶层没 height, 去
    requested_formats 里找视频流那一路。
    """
    if format_kind == "mp3":
        abr = info.get("abr")
        return f"{round(abr)} kbps" if abr else ""
    height = info.get("height")
    if not height:
        for f in info.get("requested_formats") or []:
            if f.get("height"):
                height = f["height"]
                break
    if height:
        return f"{height}p"
    res = info.get("resolution")
    return str(res) if res and res != "audio only" else ""


class DownloadJob(QObject):
    """单个下载任务. QObject + 信号; run() 在 worker 线程被调用."""

    # percent (0..1), speed_str, eta_str
    progress = pyqtSignal(float, str, str)
    # 状态字符串变化 (JobStatus.value); 另有两个不属于 JobStatus 的特殊事件:
    #   "info_fetched" —— 元信息到手, title 此时已写入
    #   "retrying"     —— 本次尝试失败, 正在重试 (attempt 已自增)
    status_changed = pyqtSignal(str)
    # 完成: ok=True 时 detail=output_path, ok=False 时 detail=error/cancel reason
    finished = pyqtSignal(bool, str)

    def __init__(self, url: str, options: DownloadOptions) -> None:
        super().__init__()
        self.id = str(uuid4())
        self.url = url
        self.options = options
        self.status = JobStatus.QUEUED
        self.title: str = ""
        self.uploader: str = ""
        self.duration_sec: int = 0
        self.output_path: Path | None = None
        self.actual_quality: str = ""   # 实际下到的画质 (mp4=分辨率 / mp3=码率), done 后填
        self.error: str = ""
        self.attempt = 0          # 已用掉的尝试次数, UI 用来显示 "重试 2/3"
        self.max_attempts = _MAX_ATTEMPTS
        self._cancel_requested = False

    # ---------- worker entry ----------

    def run(self) -> None:
        """重试外壳: 失败就整轮重来 (含重新 extract_info), 取消则立即退出."""
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            self.attempt = attempt
            try:
                self._attempt_once()
            except _CancelledByUser:
                self._set_status(JobStatus.CANCELLED)
                self.finished.emit(False, "cancelled")
                return
            except Exception as e:
                last_error = ytdlp_wrapper.strip_ansi(str(e))
                log.warning(
                    "下载失败 (第 {}/{} 次): {} —— {}",
                    attempt, self.max_attempts, self.url, last_error,
                )
                # 用户已点取消: 别再重试 (否则还要白跑一整轮 extract_info 才停)
                if self._cancel_requested:
                    self._set_status(JobStatus.CANCELLED)
                    self.finished.emit(False, "cancelled")
                    return
                if attempt < self.max_attempts:
                    self.status_changed.emit("retrying")
                    if self._sleep_cancellable(_backoff_for(attempt)):
                        self._set_status(JobStatus.CANCELLED)
                        self.finished.emit(False, "cancelled")
                        return
            else:
                if attempt > 1:
                    log.info("下载成功 (第 {} 次尝试): {}", attempt, self.url)
                self._set_status(JobStatus.DONE)
                self.finished.emit(True, str(self.output_path))
                return

        log.error("下载放弃, 已尝试 {} 次: {}", self.max_attempts, self.url)
        self.error = last_error
        self._set_status(JobStatus.ERROR)
        self.finished.emit(False, last_error)

    def _sleep_cancellable(self, seconds: float) -> bool:
        """分片睡眠, 期间响应取消. 返回 True 表示被取消."""
        waited = 0.0
        while waited < seconds:
            if self._cancel_requested:
                return True
            QThread.msleep(200)
            waited += 0.2
        return self._cancel_requested

    def _attempt_once(self) -> None:
        """跑一次完整的提取 + 下载. 失败直接抛, 由 run() 决定是否重试.

        **每次都重新 extract_info** —— 403 的成因是拿到的直链本身是坏的, 复用上一轮的
        info 重下等于拿同一条坏链接再撞一次墙, 必须重新提取换一批链接。
        """
        # 注: 状态 RUNNING 由 DownloadService._dispatch 提前设置, 这里不重复.
        def hook(d: dict) -> None:
            if self._cancel_requested:
                raise _CancelledByUser()
            status = d.get("status")
            if status == "downloading":
                downloaded = d.get("downloaded_bytes", 0) or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                percent = (downloaded / total) if total else 0.0
                speed = d.get("_speed_str", "") or ""
                eta = d.get("_eta_str", "") or ""
                self.progress.emit(percent, speed.strip(), eta.strip())
            elif status == "finished":
                self.progress.emit(1.0, "", "")

        opts = ytdlp_wrapper.build_ydl_opts(self.options, hook)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(self.url, download=False)
            # 单视频, 不应当出 entries; 防御性处理
            if "entries" in info and info["entries"]:
                info = info["entries"][0]
            self.title = str(info.get("title") or self.url)
            self.uploader = str(info.get("uploader") or "")
            self.duration_sec = int(info.get("duration") or 0)
            self.status_changed.emit("info_fetched")

            ydl.process_info(info)
            fn = ydl.prepare_filename(info)
            # mp3 转换会改后缀
            if self.options.format_kind == "mp3":
                fn = str(Path(fn).with_suffix(".mp3"))
            self.output_path = Path(fn)
            self.actual_quality = _extract_quality(info, self.options.format_kind)

    # ---------- public API ----------

    def cancel(self) -> None:
        """请求取消. 实际终止由 progress_hook 在下一个 tick 触发."""
        if self.status in (JobStatus.RUNNING, JobStatus.QUEUED):
            self._cancel_requested = True

    # ---------- internal ----------

    def _set_status(self, s: JobStatus) -> None:
        self.status = s
        self.status_changed.emit(s.value)


class DownloadService(QObject):
    """全局下载队列管理. 最多 MAX_CONCURRENT 个并发."""

    job_added = pyqtSignal(object)  # DownloadJob

    MAX_CONCURRENT = 2

    def __init__(self) -> None:
        super().__init__()
        self._jobs: list[DownloadJob] = []
        self._running: list[DownloadJob] = []
        self._threads: dict[str, QThread] = {}

    def add_job(self, url: str, options: DownloadOptions) -> DownloadJob:
        clean, stripped = ytdlp_wrapper.clean_url(url)
        if stripped:
            log.info("URL 清洗去掉参数 {}: {}", stripped, clean)

        if options.ffmpeg_location is None:
            ff = ffmpeg_dir()
            if ff:
                options = replace(options, ffmpeg_location=ff)

        job = DownloadJob(clean, options)
        self._jobs.append(job)
        # 绑定方法 (非无 context 的 lambda): 发射方 job 在 worker 线程、接收方 self 在
        # 主线程 → AutoConnection 走 QueuedConnection, 收尾逻辑在主线程跑, 避免在
        # worker 线程里动共享状态 / 误删仍在运行的线程 (曾致 qFatal "QThread destroyed
        # while running"). 槽内用 self.sender() 取回是哪个 job.
        job.finished.connect(self._on_job_finished)
        log.info("加入队列: {}", clean)
        self.job_added.emit(job)
        self._dispatch()
        return job

    def retry_job(self, job: DownloadJob) -> DownloadJob | None:
        """手动重试一个失败/已取消的任务. 返回新建的 job; 状态不允许重试时返回 None.

        **新建 job 而不是原地重置旧对象重跑** —— 旧 job 的线程亲和性还指着那个
        已经结束并 deleteLater 掉的 QThread, 从主线程再 moveToThread 会报
        "Current thread is not the object's thread" 甚至崩。linksync 那边踩过同样
        的坑 (每次启动监听都新建 service, 不复用), 这里沿用同一约定。

        url 和 options 从旧 job 直接取 —— 它们在 add_job 里已经清洗过 URL、
        注入过 ffmpeg 路径, 不必重做。
        """
        if job.status not in (JobStatus.ERROR, JobStatus.CANCELLED):
            log.warning("任务状态为 {}, 不可重试: {}", job.status.value, job.url)
            return None

        new_job = DownloadJob(job.url, job.options)
        self._jobs.append(new_job)
        new_job.finished.connect(self._on_job_finished)
        log.info("手动重试: {}", job.url)
        self._dispatch()
        return new_job

    def jobs(self) -> list[DownloadJob]:
        return list(self._jobs)

    def shutdown(self) -> None:
        """应用关闭时同步收尾: 取消在跑的任务, quit+wait 所有线程."""
        for job in list(self._running):
            job.cancel()
        for thread in list(self._threads.values()):
            if thread.isRunning():
                thread.quit()
                thread.wait(3000)
        self._threads.clear()

    # ---------- internal ----------

    def _dispatch(self) -> None:
        while len(self._running) < self.MAX_CONCURRENT:
            next_job = next((j for j in self._jobs if j.status == JobStatus.QUEUED), None)
            if next_job is None:
                return
            # 提前置 RUNNING: worker 线程才会真正开始 run(), 但状态切换必须
            # 在 dispatch 这一拍发生, 否则下一次循环还会把同一个 job 选出来,
            # 导致 moveToThread/start 重复 (会发出双份信号 + 双份 history).
            self._running.append(next_job)
            next_job._set_status(JobStatus.RUNNING)

            # 认 self 作父: 即使 self._threads 里的引用被移除, C++ 线程对象归 self 所有,
            # Python GC 不会把"仍在运行的线程"删掉 → 杜绝 qFatal 崩溃.
            thread = QThread(self)
            next_job.moveToThread(thread)
            thread.started.connect(next_job.run)
            next_job.finished.connect(thread.quit)
            # 只在线程真正 finished 之后再摘除 / 释放 (此时不再 running, 安全)
            thread.finished.connect(self._on_thread_finished)
            thread.finished.connect(thread.deleteLater)
            self._threads[next_job.id] = thread
            thread.start()

    def _on_job_finished(self) -> None:
        """job.finished 的收尾 (主线程 queued). 用 sender() 取回是哪个 job.

        不在这里删线程: 此刻 worker 线程往往还没 quit 完, 删引用有崩溃风险;
        线程的摘除放到 _on_thread_finished (thread 真 finished 后).
        """
        job = self.sender()
        if not isinstance(job, DownloadJob):
            return
        if job in self._running:
            self._running.remove(job)
        self._record_history(job)
        self._dispatch()

    def _on_thread_finished(self) -> None:
        """线程真正结束后从追踪表摘除 (主线程 queued). deleteLater 另行释放 C++ 对象."""
        thread = self.sender()
        for jid, t in list(self._threads.items()):
            if t is thread:
                del self._threads[jid]
                break

    @staticmethod
    def _record_history(job: DownloadJob) -> None:
        if job.status != JobStatus.DONE or not job.output_path:
            return
        try:
            size = job.output_path.stat().st_size if job.output_path.exists() else 0
        except OSError:
            size = 0
        with connection() as conn:
            conn.execute(
                "INSERT INTO download_history "
                "(url, output_path, format, quality, file_size, duration_sec, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    job.url, str(job.output_path),
                    job.options.format_kind, job.options.quality,
                    size, job.duration_sec, "done",
                ),
            )
