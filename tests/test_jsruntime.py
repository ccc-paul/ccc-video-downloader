"""jsruntime 单测 + build_ydl_opts 里的 JS 运行时接线.

背景: 2026-08 模块 2 下载报 HTTP 403 Forbidden。根因是 yt-dlp 版本过旧 + 本机没有
任何 JS 运行时 —— YouTube 用 JS 算 nsig/签名挑战, 没有运行时就退回 android_vr
客户端, 直链容易 403。这些用例盯住修复不被回退。
"""
from __future__ import annotations

from pathlib import Path

from app.core import ytdlp_wrapper
from app.core.ytdlp_wrapper import DownloadOptions
from app.infra import jsruntime


def noop_hook(d):
    pass


def opts_for(tmp_path: Path) -> DownloadOptions:
    return DownloadOptions(format_kind="mp4", quality="1080", output_dir=tmp_path)


class TestFindJsRuntime:
    def test_prefers_vendor_over_path(self, tmp_path, monkeypatch):
        """vendor 里的版本是我们验证过的, 要盖过用户机器上可能很老的全局安装."""
        # 文件名按平台取 —— 写死 "deno.exe" 会让这条用例在 mac/Linux 上必挂
        # (那边 _EXE_SUFFIX 是空串, find_js_runtime 找的是 vendor/deno/deno).
        vendor_deno = tmp_path / "vendor" / "deno" / f"deno{jsruntime._EXE_SUFFIX}"
        vendor_deno.parent.mkdir(parents=True)
        vendor_deno.write_text("")
        monkeypatch.setattr(jsruntime, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(jsruntime.shutil, "which", lambda n: r"C:\global\deno.exe")

        name, path = jsruntime.find_js_runtime()
        assert name == "deno"
        assert path == vendor_deno

    def test_falls_back_to_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(jsruntime, "_PROJECT_ROOT", tmp_path)  # vendor 空
        monkeypatch.setattr(
            jsruntime.shutil, "which", lambda n: r"C:\global\node.exe" if n == "node" else None)

        name, path = jsruntime.find_js_runtime()
        assert name == "node"
        assert path == Path(r"C:\global\node.exe")

    def test_priority_order(self, tmp_path, monkeypatch):
        """deno 优先级高于 node —— 跟 yt-dlp 自己的排序一致."""
        monkeypatch.setattr(jsruntime, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(jsruntime.shutil, "which", lambda n: rf"C:\g\{n}.exe")
        assert jsruntime.find_js_runtime()[0] == "deno"

    def test_none_when_nothing_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(jsruntime, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(jsruntime.shutil, "which", lambda n: None)
        assert jsruntime.find_js_runtime() is None
        assert jsruntime.is_available() is False
        assert jsruntime.js_runtimes_opt() is None


class TestJsRuntimesOpt:
    def test_shape_matches_ytdlp_api(self, tmp_path, monkeypatch):
        """yt-dlp 要的是 {runtime: {'path': ...}}; 形状错了会 ValueError."""
        monkeypatch.setattr(
            jsruntime, "find_js_runtime", lambda: ("deno", Path(r"C:\v\deno.exe")))
        assert jsruntime.js_runtimes_opt() == {"deno": {"path": r"C:\v\deno.exe"}}


class TestBuildYdlOpts:
    def test_wires_js_runtime_and_ejs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            ytdlp_wrapper.jsruntime, "js_runtimes_opt",
            lambda: {"deno": {"path": r"C:\v\deno.exe"}})

        opts = ytdlp_wrapper.build_ydl_opts(opts_for(tmp_path), noop_hook)

        assert opts["js_runtimes"] == {"deno": {"path": r"C:\v\deno.exe"}}
        # 光有运行时不够, 还要允许拉 EJS 求解脚本, 否则 n challenge 解不开
        assert opts["remote_components"] == ["ejs:github"]

    def test_omits_keys_when_no_runtime(self, tmp_path, monkeypatch):
        """找不到运行时就**不传** key, 让 yt-dlp 走自己的默认;
        传空 dict 会把默认的 deno 也关掉, 更糟。"""
        monkeypatch.setattr(ytdlp_wrapper.jsruntime, "js_runtimes_opt", lambda: None)

        opts = ytdlp_wrapper.build_ydl_opts(opts_for(tmp_path), noop_hook)

        assert "js_runtimes" not in opts
        assert "remote_components" not in opts

    def test_warnings_not_silenced(self, tmp_path):
        """no_warnings 会把 '没有 JS 运行时' 这类关键线索吞掉 —— 不许再设."""
        opts = ytdlp_wrapper.build_ydl_opts(opts_for(tmp_path), noop_hook)
        assert not opts.get("no_warnings")
        assert opts.get("logger") is not None

    def test_logger_has_ytdlp_required_methods(self, tmp_path):
        logger = ytdlp_wrapper.build_ydl_opts(opts_for(tmp_path), noop_hook)["logger"]
        for method in ("debug", "warning", "error"):
            assert callable(getattr(logger, method))

    def test_logger_survives_braces(self, tmp_path):
        """yt-dlp 的消息里可能带 {} (URL/JSON), loguru 的 format 会当占位符炸掉."""
        logger = ytdlp_wrapper.build_ydl_opts(opts_for(tmp_path), noop_hook)["logger"]
        logger.warning("nsig extraction failed: {'n': 'abc'} {0}")
        logger.error("HTTP Error 403: Forbidden {")
        logger.debug("[debug] fmt {x}")
