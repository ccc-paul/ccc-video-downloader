"""日志: loguru, 控制台 + APPDATA 下按天滚动的文件 (格式见设计文档 §7.1)."""
from __future__ import annotations

import sys

from loguru import logger

from app.infra.config import APPDATA_DIR, ensure_appdata_dir

_LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <5} | "
    "{extra[module]: <11} | "
    "{message}"
)

_initialized = False


def setup_logging(level: str = "INFO") -> None:
    """配置 loguru sinks. 多次调用安全 (幂等)."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    logger.remove()
    logger.configure(extra={"module": "system"})

    # 打包成 --windowed (无控制台) 后双击启动时 sys.stderr 是 None,
    # loguru.add(None) 会抛 "Cannot log to objects of type 'NoneType'" 崩溃。
    # 有真实 stderr 才加控制台 sink; 否则只写文件 sink。
    if sys.stderr is not None:
        logger.add(sys.stderr, format=_LOG_FORMAT, level=level)

    ensure_appdata_dir()
    log_dir = APPDATA_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(
        log_dir / "app-{time:YYYY-MM-DD}.log",
        format=_LOG_FORMAT,
        level="DEBUG",
        rotation="00:00",
        retention="60 days",
        encoding="utf-8",
    )


def get_logger(module: str):
    """带模块标签的 logger; 模块名建议: system/ui/livestream/download/linksync/slidegen/ccc_db/youtube/grok."""
    return logger.bind(module=module)


def mask(secret: str | None, prefix: int = 4, suffix: int = 4) -> str:
    """API Key / 密码脱敏: 仅前 prefix + 后 suffix 位."""
    if not secret:
        return "<empty>"
    if len(secret) <= prefix + suffix:
        return "*" * len(secret)
    return f"{secret[:prefix]}…{secret[-suffix:]}"
