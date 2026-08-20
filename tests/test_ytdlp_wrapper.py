"""ytdlp_wrapper 单测 (纯函数, 无网络/无 yt-dlp 下载)."""
from __future__ import annotations

from pathlib import Path

from app.core import ytdlp_wrapper as yw


class TestCleanUrl:
    def test_strips_list_param(self):
        url = "https://www.youtube.com/watch?v=abc123&list=PLxyz&index=3"
        clean, stripped = yw.clean_url(url)
        assert "list=" not in clean
        assert "index=" not in clean
        assert "v=abc123" in clean
        assert "list" in stripped
        assert "index" in stripped

    def test_keeps_v_param(self):
        clean, _ = yw.clean_url("https://youtube.com/watch?v=HfE3WNcdDTk")
        assert clean == "https://youtube.com/watch?v=HfE3WNcdDTk"

    def test_keeps_unrelated_params(self):
        clean, stripped = yw.clean_url("https://youtube.com/watch?v=abc&t=42s")
        assert "t=42s" in clean
        assert stripped == []

    def test_handles_no_query(self):
        clean, stripped = yw.clean_url("https://youtu.be/abc123")
        assert clean == "https://youtu.be/abc123"
        assert stripped == []

    def test_strips_pp_and_radio(self):
        url = "https://youtube.com/watch?v=x&pp=ygUF&start_radio=1"
        clean, stripped = yw.clean_url(url)
        assert "pp" in stripped
        assert "start_radio" in stripped


class TestBuildYdlOpts:
    def _opts(self, **kw):
        defaults = dict(
            format_kind="mp4",
            quality="1080",
            output_dir=Path("/tmp/out"),
            ffmpeg_location=Path("/usr/bin"),
        )
        defaults.update(kw)
        return yw.DownloadOptions(**defaults)

    def test_mp4_1080(self):
        opts = yw.build_ydl_opts(self._opts(format_kind="mp4", quality="1080"), lambda d: None)
        assert "bestvideo[height<=1080][ext=mp4]" in opts["format"]
        assert opts["merge_output_format"] == "mp4"
        assert opts["ffmpeg_location"] == str(Path("/usr/bin"))

    def test_mp4_best(self):
        opts = yw.build_ydl_opts(self._opts(format_kind="mp4", quality="best"), lambda d: None)
        assert opts["format"] == "bestvideo+bestaudio/best"

    def test_mp3_192(self):
        opts = yw.build_ydl_opts(self._opts(format_kind="mp3", quality="192"), lambda d: None)
        assert opts["format"] == "bestaudio/best"
        pp = opts["postprocessors"][0]
        assert pp["key"] == "FFmpegExtractAudio"
        assert pp["preferredcodec"] == "mp3"
        assert pp["preferredquality"] == "192"

    def test_outtmpl_combines_dir_and_template(self):
        opts = yw.build_ydl_opts(
            self._opts(output_dir=Path("/x"), filename_template="%(title)s.%(ext)s"),
            lambda d: None,
        )
        assert opts["outtmpl"].endswith("%(title)s.%(ext)s")
        assert "/x" in opts["outtmpl"] or "\\x" in opts["outtmpl"]

    def test_noplaylist_always_true(self):
        opts = yw.build_ydl_opts(self._opts(), lambda d: None)
        assert opts["noplaylist"] is True

    def test_no_ffmpeg_location_omits_key(self):
        opts = yw.build_ydl_opts(self._opts(ffmpeg_location=None), lambda d: None)
        assert "ffmpeg_location" not in opts
