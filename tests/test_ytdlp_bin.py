"""yt-dlp 外挂二进制的探测与缓存.

重点在**缓存**和**超时**: mac 上官方 yt-dlp 是 PyInstaller onefile, 每次执行都要
把 ~37MB 解到临时目录, 实测 `--version` 单次 8~12s。所以
1) 默认 8s 超时在 mac 上必然误报"不可用" ⇒ 超时按平台放宽;
2) 启动时日志和状态栏都要问版本 ⇒ 问一次就够, 结果缓存起来。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.infra import ytdlp_bin


@pytest.fixture(autouse=True)
def _clear_cache():
    ytdlp_bin._probe_cache = None
    yield
    ytdlp_bin._probe_cache = None


class TestProbeCache:
    def test_只跑一次(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ytdlp_bin, "find_ytdlp", lambda: Path("/fake/yt-dlp"))
        monkeypatch.setattr(
            ytdlp_bin, "run_version",
            lambda exe, *a, **kw: (calls.append(a) or (True, "2026.08.19")),
        )

        assert ytdlp_bin.probe() == (True, "2026.08.19")
        assert ytdlp_bin.probe() == (True, "2026.08.19")
        assert ytdlp_bin.is_available() is True
        assert len(calls) == 1, "第二次该走缓存, 不该再起一次进程"

    def test_refresh_强制重跑(self, monkeypatch):
        versions = iter(["2026.08.19", "2026.09.01"])
        monkeypatch.setattr(ytdlp_bin, "find_ytdlp", lambda: Path("/fake/yt-dlp"))
        monkeypatch.setattr(ytdlp_bin, "run_version",
                            lambda exe, *a, **kw: (True, next(versions)))

        assert ytdlp_bin.probe()[1] == "2026.08.19"
        assert ytdlp_bin.probe(refresh=True)[1] == "2026.09.01"
        assert ytdlp_bin.probe()[1] == "2026.09.01", "刷新后的值也要进缓存"

    def test_找不到时不缓存成功态(self, monkeypatch):
        monkeypatch.setattr(ytdlp_bin, "find_ytdlp", lambda: None)
        ok, detail = ytdlp_bin.probe()
        assert ok is False and "未找到" in detail


class TestProbeTimeout:
    def test_探测超时按平台放宽(self):
        # mac 的 onefile 每次解包 8~12s, 8s 默认值必然误报不可用
        assert ytdlp_bin._PROBE_TIMEOUT >= 30.0 or ytdlp_bin.sys.platform != "darwin"

    def test_超时值真的传给了_run_version(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(ytdlp_bin, "find_ytdlp", lambda: Path("/fake/yt-dlp"))
        monkeypatch.setattr(
            ytdlp_bin, "run_version",
            lambda exe, *a, **kw: (seen.update(kw) or (True, "x")),
        )
        ytdlp_bin.probe()
        assert seen.get("timeout") == ytdlp_bin._PROBE_TIMEOUT


class TestSelfUpdate:
    def test_更新后把新版本写进缓存(self, monkeypatch):
        monkeypatch.setattr(ytdlp_bin, "find_ytdlp", lambda: Path("/fake/yt-dlp"))
        seq = iter([(True, "2026.08.19"), (True, "updated"), (True, "2026.09.01")])
        monkeypatch.setattr(ytdlp_bin, "run_version", lambda exe, *a, **kw: next(seq))

        ytdlp_bin.probe()                      # 打底: 缓存 2026.08.19
        changed, message = ytdlp_bin.self_update()

        assert changed is True
        assert "2026.08.19 → 2026.09.01" in message
        assert ytdlp_bin.probe()[1] == "2026.09.01", "状态栏读缓存就该看到新版本"

    def test_更新失败不致命(self, monkeypatch):
        monkeypatch.setattr(ytdlp_bin, "find_ytdlp", lambda: Path("/fake/yt-dlp"))
        seq = iter([(True, "2026.08.19"), (False, "网络不通")])
        monkeypatch.setattr(ytdlp_bin, "run_version", lambda exe, *a, **kw: next(seq))

        ytdlp_bin.probe()
        changed, message = ytdlp_bin.self_update()
        assert changed is False and "不影响使用" in message


class TestCancel:
    """关窗时要能把探测/更新子进程掐掉 —— 否则后台线程卡在 communicate 上,
    QThread 带着未结束的线程被销毁, 进程 abort。"""

    def test_取消后不再起新进程(self, monkeypatch):
        from app.infra import probe as probe_mod

        monkeypatch.setattr(probe_mod, "_cancelled", False)
        monkeypatch.setattr(probe_mod, "_live", set())

        def _boom(*a, **kw):
            raise AssertionError("取消之后不该再起子进程")

        monkeypatch.setattr(probe_mod.subprocess, "Popen", _boom)
        probe_mod.kill_running()

        ok, detail = probe_mod.run_version(Path("/fake/yt-dlp"), "--version")
        assert ok is False and detail == "已取消"

    def test_kill_running_不因进程已退出而抛异常(self, monkeypatch):
        from app.infra import probe as probe_mod

        class _Dead:
            pid = 999999

            def kill(self):
                raise OSError("已经没了")

        monkeypatch.setattr(probe_mod, "_cancelled", False)
        monkeypatch.setattr(probe_mod, "_live", {_Dead()})
        probe_mod.kill_running()  # 不抛就算过

    def test_取消不许污染探测缓存(self, monkeypatch):
        """关窗掐掉的探测不是"探测失败" —— 不能顶掉已经探到的真版本号。

        没这条护栏时: 关窗瞬间缓存被写成 (False, "已取消"), 状态栏和日志跟着报
        "yt-dlp: 不可用 —— 已取消", 像是 yt-dlp 坏了, 其实是我们自己掐的。
        """
        from app.infra import probe as probe_mod

        monkeypatch.setattr(probe_mod, "_cancelled", False)
        monkeypatch.setattr(ytdlp_bin, "find_ytdlp", lambda: Path("/fake/yt-dlp"))
        monkeypatch.setattr(ytdlp_bin, "run_version",
                            lambda exe, *a, **kw: (True, "2026.08.19"))
        assert ytdlp_bin.probe()[1] == "2026.08.19"

        # 用户点了关闭: 之后的探测一律被掐
        monkeypatch.setattr(probe_mod, "_cancelled", True)
        monkeypatch.setattr(ytdlp_bin, "run_version",
                            lambda exe, *a, **kw: (False, "已取消"))

        assert ytdlp_bin.probe(refresh=True) == (True, "2026.08.19")
        assert ytdlp_bin.probe() == (True, "2026.08.19"), "缓存不该被'已取消'顶掉"

    def test_更新中途关窗不拿已取消当版本号(self, monkeypatch):
        """曾经拼出过 "yt-dlp 已更新: 2026.08.19 → 已取消" 这种自相矛盾的日志:
        更新命令跑成了, 回头问版本号时被关窗掐掉, "已取消"就被当成新版本号了。"""
        from app.infra import probe as probe_mod

        monkeypatch.setattr(probe_mod, "_cancelled", False)
        monkeypatch.setattr(ytdlp_bin, "find_ytdlp", lambda: Path("/fake/yt-dlp"))

        def _run(exe, *args, **kw):
            if args and args[0] == "--update-to":
                return True, "updated"          # 更新本身赶在关窗前跑完了
            if probe_mod.is_cancelled():
                return False, "已取消"           # 回头问版本号时被掐
            return True, "2026.08.19"

        monkeypatch.setattr(ytdlp_bin, "run_version", _run)
        ytdlp_bin.probe()                        # 打底: 缓存 2026.08.19
        monkeypatch.setattr(probe_mod, "_cancelled", True)

        changed, message = ytdlp_bin.self_update()
        assert changed is False, "问不到新版本号就别声称更新了"
        assert "已取消" not in message, f"'已取消'不是版本号: {message}"
        assert "打断" in message
        assert ytdlp_bin.probe()[1] == "2026.08.19", "缓存要保住上一次的真版本号"
