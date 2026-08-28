"""所有测试共用的隔离.

**绝不碰开发机上真实的配置文件** —— 2026-08-27 踩过一次: 新加的
test_custom_filename 里点「加入下载队列」会连带跑 _remember_options(), 把 pytest
的临时目录写进了真实的 config.json。用户下次打开程序, 「保存到」就成了
`/private/var/folders/.../pytest-of-xxx/test_撞名自动补编号0`。

所以这条 fixture 是 **autouse** 的: 不需要记得申请, 也就没法忘。
"""
from __future__ import annotations

import pytest

from app.infra import config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """把 config 指到本次测试的临时目录, 返回配置文件路径."""
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "APPDATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    return cfg_path
