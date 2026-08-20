"""本地 SQLite 下载历史.

只有 download_history 一张表 —— 主线里的直播/链接同步/PPT 三张表随模块一起
剥掉了。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.infra.config import APPDATA_DIR, ensure_appdata_dir

DB_PATH = APPDATA_DIR / "history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS download_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    url TEXT,
    output_path TEXT,
    format TEXT,
    quality TEXT,
    file_size INTEGER,
    duration_sec INTEGER,
    status TEXT
);
"""


def init_db() -> None:
    """建表 (幂等). 应用启动时调用."""
    ensure_appdata_dir()
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """SQLite 连接上下文; 退出时 commit + close. 异常时回滚."""
    ensure_appdata_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
