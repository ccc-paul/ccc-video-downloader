"""logger.setup_logging 的健壮性测试 (无网络)."""
from __future__ import annotations

import app.infra.logger as lg


def _reset(monkeypatch, tmp_path):
    """把 logger 恢复到未初始化, 文件 sink 指向 tmp, 便于反复调用 setup_logging."""
    monkeypatch.setattr(lg, "_initialized", False)
    monkeypatch.setattr(lg, "APPDATA_DIR", tmp_path)
    lg.logger.remove()


def test_setup_logging_survives_none_stderr(monkeypatch, tmp_path):
    """模拟 PyInstaller --windowed 双击启动: sys.stderr 为 None.

    回归: 曾经 logger.add(sys.stderr) 直接抛 "Cannot log to objects of type
    'NoneType'", 导致打包后双击闪退。
    """
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(lg.sys, "stderr", None)

    lg.setup_logging()  # 不应抛异常
    lg.get_logger("test").info("hello from windowed mode")

    # 控制台 sink 跳过了, 但文件 sink 仍应建立并写入
    assert (tmp_path / "logs").exists()
    lg.logger.remove()


def test_setup_logging_with_stderr_adds_console(monkeypatch, tmp_path):
    """有真实 stderr 时正常配置, 不抛异常."""
    _reset(monkeypatch, tmp_path)
    lg.setup_logging()
    lg.get_logger("test").info("hello")
    assert (tmp_path / "logs").exists()
    lg.logger.remove()
