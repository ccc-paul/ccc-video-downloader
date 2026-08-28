"""队列行的布局: 长标题不许把控件顶到可视区外 (2026-08-24 反馈).

截图里的现象: 粘一条标题很长的视频, 队列行右边的进度条和信息列被顶出窗口,
队列区域还多出一条横向滚动条。

根因是不换行的 QLabel —— 它的 minimumSizeHint 就是整串文字的宽度 (实测那条
讚美之泉的标题要 826px), 布局压不下去, 只能把行撑到 1348px, 而可视区只有 1052px。
修法是换行 + 横向 Ignored (不拿 sizeHint 说话) + 一个宽度下限。
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QScrollArea

from app.core.ytdlp_wrapper import DownloadOptions
from app.infra.i18n import init_i18n
from app.services.download_service import DownloadJob
from app.ui.pages.downloader_page import _TITLE_MIN_WIDTH, DownloaderPage, _JobRowWidget

# 真实撞上的那条 (讚美之泉), 129 字符
LONG_TITLE = (
    "【主我敬拜祢 Lord, I Worship You ／ 哈利路亞 Hallelujah】官方歌詞版MV "
    "(Official Lyrics MV) - 讚美之泉敬拜讚美 (3) - 讚美之泉 Stream Of Praise"
)
# 更狠的: 280 字符且一个空格都没有 —— 按词换行在这种串上是失效的
NO_SPACE = "https://www.youtube.com/watch?v=" + "a1B2c3D4e5" * 25


@pytest.fixture(scope="module")
def _qapp():
    init_i18n()
    yield QApplication.instance() or QApplication([])


def _row(_qapp, title: str) -> _JobRowWidget:
    job = DownloadJob("https://www.youtube.com/watch?v=j8pQHrnc348",
                      DownloadOptions("mp4", "1080", Path("/tmp")))
    job.title = title
    row = _JobRowWidget(job)
    row._name_label.setText(title)
    return row


class TestRowWidth:
    @pytest.mark.parametrize("title", [LONG_TITLE, NO_SPACE], ids=["长标题", "无空格超长串"])
    def test_行的最小宽度不随标题变长(self, _qapp, title):
        """行的最小宽度必须由控件决定, 而不是由文字长度决定。

        窗口最小宽度是 900 (MainWindow.setMinimumSize), 行的最小宽度超过它,
        队列区就必然出横向滚动条、右侧控件被顶出去。
        """
        short = _row(_qapp, "短标题").minimumSizeHint().width()
        long_ = _row(_qapp, title).minimumSizeHint().width()

        assert long_ == short, "行的最小宽度被标题撑大了 —— 标签又开始拿 sizeHint 说话"
        assert long_ < 900, f"行最小宽度 {long_} 超过窗口最小宽度 900"

    def test_标题列有宽度下限(self, _qapp):
        """也不能反过来被进度条/信息列挤成一条缝。"""
        row = _row(_qapp, LONG_TITLE)
        assert row._name_label.minimumWidth() == _TITLE_MIN_WIDTH
        assert row._url_label.minimumWidth() == _TITLE_MIN_WIDTH


class TestWrap:
    @pytest.mark.parametrize("title", [LONG_TITLE, NO_SPACE], ids=["长标题", "无空格超长串"])
    def test_放不下就换行而不是撑宽(self, _qapp, title):
        row = _row(_qapp, title)
        label = row._name_label
        assert label.wordWrap() is True

        one_line = label.heightForWidth(10_000)      # 宽度管够时的高度 = 一行
        wrapped = label.heightForWidth(530)          # 实际能分到的宽度
        assert wrapped > one_line, "没换行 —— 无空格的串要靠 WrapAnywhere 才能断开"


class TestInfoColumn:
    """信息列现在要装文件名 (文件名 · 画质 · 大小 · 时间), 同样不能把行撑爆。"""

    def test_长文件名不撑宽行(self, _qapp):
        short = _row(_qapp, "短标题")
        short._info_label.setText("1080p  ·  14.1 MB  ·  20:06:32")
        base = short.minimumSizeHint().width()

        long_ = _row(_qapp, "短标题")
        long_._info_label.setText(f"{LONG_TITLE}.mp4  ·  1080p  ·  14.1 MB  ·  20:06:32")

        assert long_.minimumSizeHint().width() == base
        assert long_._info_label.wordWrap() is True

    def test_信息列不许用_Ignored(self, _qapp):
        """踩过: Ignored 会让本列的 sizeHint 被无视, 空间被 stretch=1 的标题列全吃掉,
        本列再按 minimumWidth 摆出去就超出行宽 —— 进度条和信息列又被顶出可视区。"""
        from PyQt6.QtWidgets import QSizePolicy

        row = _row(_qapp, "短标题")
        assert row._info_label.sizePolicy().horizontalPolicy() != QSizePolicy.Policy.Ignored
        assert row._info_label.maximumWidth() < 10_000, "得有上限, 否则又会抢标题的空间"


class TestInPage:
    """放进真实页面 (含 QScrollArea) 里验最终效果。"""

    def test_控件不被顶出可视区(self, _qapp):
        page = DownloaderPage()
        page.resize(1100, 720)
        page.show()          # 不 show 的话滚动区的 viewport 还没拿到真实宽度
        QApplication.processEvents()

        job = DownloadJob("https://www.youtube.com/watch?v=j8pQHrnc348",
                          DownloadOptions("mp4", "1080", Path("/tmp")))
        job.title = LONG_TITLE
        page._add_job_row(job)

        scroll = page.findChild(QScrollArea)
        row = scroll.widget().findChild(_JobRowWidget)
        row._name_label.setText(LONG_TITLE)
        row._info_label.setText(f"{LONG_TITLE}.mp4  ·  1080p  ·  14.1 MB  ·  20:06:32")
        page.layout().activate()
        scroll.widget().layout().activate()
        QApplication.processEvents()

        viewport = scroll.viewport().width()
        assert scroll.widget().minimumSizeHint().width() <= viewport, (
            "队列容器比可视区还宽 —— 会出横向滚动条, 右侧控件被推出去"
        )
        for name, widget in (("进度条", row._progress), ("信息列", row._info_label)):
            right = widget.mapTo(scroll.widget(), QPoint(0, 0)).x() + widget.width()
            assert right <= viewport, f"{name}右边缘 {right} 超出可视区 {viewport}"

    def test_换行后文字没被截断(self, _qapp):
        """QHBoxLayout 对 heightForWidth 支持有限, 换行后行高不够会把第二行切掉。"""
        page = DownloaderPage()
        page.resize(1100, 720)
        page.show()          # 不 show 的话滚动区的 viewport 还没拿到真实宽度
        QApplication.processEvents()
        job = DownloadJob("https://www.youtube.com/watch?v=j8pQHrnc348",
                          DownloadOptions("mp4", "1080", Path("/tmp")))
        job.title = LONG_TITLE
        page._add_job_row(job)

        scroll = page.findChild(QScrollArea)
        row = scroll.widget().findChild(_JobRowWidget)
        row._name_label.setText(LONG_TITLE)
        page.layout().activate()
        scroll.widget().layout().activate()
        QApplication.processEvents()

        label = row._name_label
        assert label.height() >= label.heightForWidth(label.width()), "换行后的文字被切掉了"
