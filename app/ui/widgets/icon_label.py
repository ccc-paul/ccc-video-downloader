"""图标化 i18n 文案的共用小工具.

约定: 队列相关的 i18n 文案都写成 "图标 空格 文字" 的形式, 例如
`"✓ 完成"` / `"⏹ 取消"`。界面上只显示图标, 文字进 tooltip ——
队列一长, 一列中文状态词既占宽又噪, 图标已经够辨识 (2026-08-16 反馈)。

文案本身保持完整是有意的: tooltip 要用, 日志/无障碍也可能要用, 不能只存图标。
"""
from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QPushButton


def split_icon_label(label: str) -> tuple[str, str]:
    """把 "✓ 完成" 拆成 ("✓", "完成").

    没有空格时 (纯图标或纯文字) 原样当图标返回, 文字部分回落成整串 ——
    调用方拿它当 tooltip 至少不会是空的。
    """
    icon, _, text = label.partition(" ")
    return icon, (text or label)


def set_icon_status(widget: QLabel, label: str) -> None:
    """给状态标签设成"只显示图标, 文字进 tooltip"."""
    icon, text = split_icon_label(label)
    widget.setText(icon)
    widget.setToolTip(text)


def icon_button(label: str, on_click, *, width: int = 40) -> QPushButton:
    """把 "📂 打开" 这种带图标的 i18n 文案做成只留图标的小按钮, 文字进 tooltip."""
    icon, text = split_icon_label(label)
    btn = QPushButton(icon)
    btn.setToolTip(text)
    btn.setFixedWidth(width)
    btn.clicked.connect(on_click)
    return btn
