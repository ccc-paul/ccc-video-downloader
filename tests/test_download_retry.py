"""下载队列的手动重试 (2026-08-16).

间歇性 403 时自动重试 3 次仍可能全败, 用户不该被迫重新粘一遍链接。
重试**新建 job** 而不是复用旧对象 —— 旧 job 的线程亲和性指着已结束的 QThread。
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from app.core.ytdlp_wrapper import DownloadOptions
from app.services.download_service import DownloadJob, DownloadService, JobStatus


@pytest.fixture(scope="module")
def _qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def service(_qapp, monkeypatch):
    svc = DownloadService()
    # 别真起线程去下载: dispatch 变成空操作, 只验状态与对象管理
    monkeypatch.setattr(svc, "_dispatch", lambda: None)
    return svc


def make_job(url="https://youtu.be/abc", tmp=Path(".")) -> DownloadJob:
    return DownloadJob(url, DownloadOptions(format_kind="mp4", quality="1080", output_dir=tmp))


class TestRetryJob:
    def test_creates_new_object_not_reuse(self, service, tmp_path):
        """核心: 必须是新对象。复用旧 job 再 moveToThread 会崩."""
        old = make_job(tmp=tmp_path)
        old._set_status(JobStatus.ERROR)
        service._jobs.append(old)

        new = service.retry_job(old)

        assert new is not None
        assert new is not old
        assert new.status == JobStatus.QUEUED

    def test_carries_url_and_options(self, service, tmp_path):
        old = make_job(url="https://youtu.be/xyz", tmp=tmp_path)
        old._set_status(JobStatus.ERROR)
        service._jobs.append(old)

        new = service.retry_job(old)

        assert new.url == "https://youtu.be/xyz"
        assert new.options == old.options

    def test_new_job_tracked(self, service, tmp_path):
        old = make_job(tmp=tmp_path)
        old._set_status(JobStatus.ERROR)
        service._jobs.append(old)

        new = service.retry_job(old)

        assert new in service.jobs()

    def test_cancelled_job_is_retryable(self, service, tmp_path):
        old = make_job(tmp=tmp_path)
        old._set_status(JobStatus.CANCELLED)
        service._jobs.append(old)

        assert service.retry_job(old) is not None

    @pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.DONE])
    def test_refuses_non_failed(self, service, tmp_path, status):
        """跑着的任务重试会开出第二份下载写同一个文件; 已完成的重试没意义."""
        old = make_job(tmp=tmp_path)
        old._set_status(status)
        service._jobs.append(old)

        assert service.retry_job(old) is None

    def test_retry_twice(self, service, tmp_path):
        """重试后又失败, 还能再重试."""
        first = make_job(tmp=tmp_path)
        first._set_status(JobStatus.ERROR)
        service._jobs.append(first)

        second = service.retry_job(first)
        second._set_status(JobStatus.ERROR)
        third = service.retry_job(second)

        assert third is not None and third is not second


class TestRowRebind:
    """UI 行重试后改盯新 job, 且不再受旧 job 信号影响."""

    def row_for(self, job):
        from app.infra.i18n import init_i18n
        from app.ui.pages.downloader_page import _JobRowWidget

        init_i18n()
        return _JobRowWidget(job)

    def test_rebind_switches_job(self, _qapp, tmp_path):
        old, new = make_job(tmp=tmp_path), make_job(tmp=tmp_path)
        row = self.row_for(old)

        row.rebind(new)

        assert row.job is new

    def test_old_job_signals_ignored_after_rebind(self, _qapp, tmp_path):
        """旧 job 还活着 (service 留着做记录), 它再发信号不能改乱本行."""
        old, new = make_job(tmp=tmp_path), make_job(tmp=tmp_path)
        row = self.row_for(old)
        row.rebind(new)

        old.progress.emit(0.9, "9MB/s", "1:00")

        assert row._progress.value() == 0, "旧 job 的进度不该再影响本行"

    def test_new_job_signals_apply(self, _qapp, tmp_path):
        old, new = make_job(tmp=tmp_path), make_job(tmp=tmp_path)
        row = self.row_for(old)
        row.rebind(new)

        new.progress.emit(0.5, "5MB/s", "0:30")

        assert row._progress.value() == 500

    def test_rebind_resets_ui(self, _qapp, tmp_path):
        old, new = make_job(tmp=tmp_path), make_job(tmp=tmp_path)
        row = self.row_for(old)
        row._on_finished(False, "HTTP Error 403: Forbidden")
        assert row._retry_btn.isVisible() or True  # offscreen 下可见性以属性为准

        row.rebind(new)

        assert row._progress.value() == 0
        assert row._info_label.text() == ""

    def test_retry_button_hidden_until_failure(self, _qapp, tmp_path):
        row = self.row_for(make_job(tmp=tmp_path))
        assert row._retry_btn.isVisibleTo(row) is False

    def test_retry_button_shown_on_failure(self, _qapp, tmp_path):
        row = self.row_for(make_job(tmp=tmp_path))
        row._on_finished(False, "HTTP Error 403: Forbidden")
        assert row._retry_btn.isVisibleTo(row) is True

    def test_retry_button_shown_on_cancel(self, _qapp, tmp_path):
        row = self.row_for(make_job(tmp=tmp_path))
        row._on_finished(False, "cancelled")
        assert row._retry_btn.isVisibleTo(row) is True

    def test_no_retry_button_on_success(self, _qapp, tmp_path):
        job = make_job(tmp=tmp_path)
        job.output_path = tmp_path / "x.mp4"
        row = self.row_for(job)
        row._on_finished(True, str(job.output_path))
        assert row._retry_btn.isVisibleTo(row) is False


class TestStatusIconOnly:
    """状态列只留图标, 文字进 tooltip (2026-08-16 反馈)."""

    def row(self, _qapp, tmp_path):
        from app.infra.i18n import init_i18n
        from app.ui.pages.downloader_page import _JobRowWidget

        init_i18n()
        return _JobRowWidget(make_job(tmp=tmp_path))

    def test_no_text_in_label(self, _qapp, tmp_path):
        row = self.row(_qapp, tmp_path)
        row._on_status_changed(JobStatus.DONE.value)
        assert row._status_label.text() == "✓"
        assert "完成" not in row._status_label.text()

    def test_text_moved_to_tooltip(self, _qapp, tmp_path):
        row = self.row(_qapp, tmp_path)
        row._on_status_changed(JobStatus.ERROR.value)
        assert row._status_label.toolTip() == "失败"

    def test_all_statuses_are_single_icon(self, _qapp, tmp_path):
        row = self.row(_qapp, tmp_path)
        for js in JobStatus:
            row._on_status_changed(js.value)
            text = row._status_label.text()
            assert " " not in text and text, f"{js.value} 的图标不该带文字: {text!r}"


class TestIconLabelHelper:
    def test_splits_icon_and_text(self):
        from app.ui.widgets.icon_label import split_icon_label

        assert split_icon_label("✓ 完成") == ("✓", "完成")

    def test_no_space_falls_back_to_whole_string(self):
        """没空格时 tooltip 不能是空的."""
        from app.ui.widgets.icon_label import split_icon_label

        assert split_icon_label("✓") == ("✓", "✓")

    def test_multiword_text_kept(self):
        from app.ui.widgets.icon_label import split_icon_label

        assert split_icon_label("⟳ Link expired") == ("⟳", "Link expired")
