"""ytdlp_wrapper 单测 (纯函数, 无网络/无 yt-dlp 下载)."""
from __future__ import annotations

from pathlib import Path

import pytest

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


def opts(**kw) -> yw.DownloadOptions:
    defaults = dict(
        format_kind="mp4",
        quality="1080",
        output_dir=Path("/tmp/out"),
        ffmpeg_location=Path("/usr/bin"),
    )
    defaults.update(kw)
    return yw.DownloadOptions(**defaults)


def arg_after(args: list[str], flag: str) -> str:
    """取某个开关后面紧跟的那个值."""
    return args[args.index(flag) + 1]


class TestH264Preference:
    """1080p 及以下必须优先挑 H.264 (2026-08-28 实测踩到).

    YouTube 的 AV1 也装在 mp4 容器里, 只写 `[ext=mp4]` 会挑到 `av01`。下载的人自己
    (新款 Mac 硬解 AV1) 看不出问题, 发给同事就是「此文件包含与 QuickTime Player
    不兼容的部分媒体」—— 用户发出去三首歌, 两首 av01 的都打不开, 唯一能放的那首
    恰好是 avc1。
    """

    @pytest.mark.parametrize("quality", ["720", "1080"])
    def test_优先_avc1(self, quality):
        selector = yw.format_selector(opts(format_kind="mp4", quality=quality))
        first = selector.split("/")[0]
        assert "vcodec^=avc1" in first, f"第一档就该点名 H.264: {selector}"
        assert f"height<={quality}" in first

    @pytest.mark.parametrize("quality", ["720", "1080"])
    def test_没有_H264_时仍能下(self, quality):
        """有的视频压根没有 H.264 —— 退回原来的挑法, 总比下不了强。"""
        selector = yw.format_selector(opts(format_kind="mp4", quality=quality))
        fallbacks = selector.split("/")[1:]
        assert any("ext=mp4" in f for f in fallbacks)
        assert fallbacks[-1] == f"best[height<={quality}]"

    @pytest.mark.parametrize("quality", ["1440", "best"])
    def test_1440_及最佳_不降到_H264(self, quality):
        """那个档位 YouTube 只有 VP9/AV1, 硬要 H.264 等于把用户要的画质降回 1080p。"""
        selector = yw.format_selector(opts(format_kind="mp4", quality=quality))
        assert "avc1" not in selector

    def test_音频也挑_aac(self):
        """Opus 一样会让 QuickTime 打不开。"""
        selector = yw.format_selector(opts(format_kind="mp4", quality="1080"))
        assert "bestaudio[ext=m4a]" in selector.split("/")[0]


class TestBuildArgs:
    def test_mp4_1080_format_selector(self):
        args = yw.build_args(opts(format_kind="mp4", quality="1080"), "URL")
        assert "bestvideo[height<=1080][vcodec^=avc1]" in arg_after(args, "-f")
        assert arg_after(args, "--merge-output-format") == "mp4"

    def test_mp4_best(self):
        args = yw.build_args(opts(quality="best"), "URL")
        assert arg_after(args, "-f") == "bestvideo+bestaudio/best"

    def test_mp3_extracts_audio(self):
        args = yw.build_args(opts(format_kind="mp3", quality="192"), "URL")
        assert "-x" in args
        assert arg_after(args, "--audio-format") == "mp3"
        assert arg_after(args, "--audio-quality") == "192K"

    def test_output_template(self):
        args = yw.build_args(opts(output_dir=Path("/x"), filename_template="%(title)s.%(ext)s"), "URL")
        assert arg_after(args, "-o").endswith("%(title)s.%(ext)s")

    def test_url_is_last(self):
        """URL 必须在最后 —— 放中间会被当成某个开关的值."""
        args = yw.build_args(opts(), "https://youtu.be/abc")
        assert args[-1] == "https://youtu.be/abc"

    def test_noplaylist_always(self):
        assert "--no-playlist" in yw.build_args(opts(), "URL")

    def test_ffmpeg_location_passed(self):
        args = yw.build_args(opts(ffmpeg_location=Path("/usr/bin")), "URL")
        assert arg_after(args, "--ffmpeg-location") == str(Path("/usr/bin"))

    def test_no_ffmpeg_location_omits_flag(self):
        assert "--ffmpeg-location" not in yw.build_args(opts(ffmpeg_location=None), "URL")

    def test_newline_and_no_simulate_and_no_quiet(self):
        """--print 会同时隐含 --simulate 和 --quiet, 两个都得关掉.

        少了 --no-quiet 的现象很隐蔽: @@T@@ / @@F@@ 照常出, 唯独一条进度都没有。
        """
        args = yw.build_args(opts(), "URL")
        assert "--newline" in args
        assert "--no-simulate" in args
        assert "--no-quiet" in args

    def test_forces_utf8_encoding(self):
        """不指定编码的话中文标题会被 yt-dlp 用 errors='ignore' 整段吃掉
        (环境变量对冻结版无效, 只能靠这个参数)."""
        args = yw.build_args(opts(), "URL")
        assert arg_after(args, "--encoding") == "utf-8"

    def test_js_runtime_wired(self, monkeypatch):
        monkeypatch.setattr(
            yw.jsruntime, "find_js_runtime", lambda: ("deno", Path(r"C:\v\deno.exe")))
        args = yw.build_args(opts(), "URL")
        assert arg_after(args, "--js-runtimes") == r"deno:C:\v\deno.exe"
        # 光有运行时不够, 还要允许拉 EJS 求解脚本
        assert arg_after(args, "--remote-components") == "ejs:github"

    def test_no_js_runtime_omits_flags(self, monkeypatch):
        monkeypatch.setattr(yw.jsruntime, "find_js_runtime", lambda: None)
        args = yw.build_args(opts(), "URL")
        assert "--js-runtimes" not in args
        assert "--remote-components" not in args

    def test_no_warnings_never_suppressed(self):
        """当初 no_warnings 吞掉「没有 JS 运行时」, 403 查了半天 —— 不许再关警告."""
        args = yw.build_args(opts(), "URL")
        assert "--no-warnings" not in args
        assert "-q" not in args and "--quiet" not in args


class TestParseMeta:
    def test_basic(self):
        e = yw.parse_meta(f"{yw.TAG_META}某视频标题|某频道|213")
        assert e.title == "某视频标题"
        assert e.uploader == "某频道"
        assert e.duration_sec == 213

    def test_title_containing_pipe(self):
        """标题里带 | 很常见 (如「教程(1/5)丨...」), 不能把标题切碎."""
        e = yw.parse_meta(f"{yw.TAG_META}前半|后半|频道|100")
        assert e.title == "前半|后半"
        assert e.uploader == "频道"

    def test_na_fields_become_empty(self):
        e = yw.parse_meta(f"{yw.TAG_META}标题|NA|NA")
        assert e.uploader == ""
        assert e.duration_sec == 0

    def test_other_lines_ignored(self):
        assert yw.parse_meta("[youtube] Extracting URL: ...") is None


class TestParseProgress:
    def test_percent_from_bytes(self):
        e = yw.parse_progress(f"{yw.TAG_PROGRESS}500|1000|NA|1.2MiB/s|00:10")
        assert e.percent == 0.5
        assert e.speed == "1.2MiB/s"
        assert e.eta == "00:10"

    def test_falls_back_to_estimate(self):
        """total_bytes 常常是 NA, 得用 total_bytes_estimate."""
        e = yw.parse_progress(f"{yw.TAG_PROGRESS}250|NA|1000|1MiB/s|00:05")
        assert e.percent == 0.25

    def test_unknown_total_gives_zero(self):
        e = yw.parse_progress(f"{yw.TAG_PROGRESS}250|NA|NA|1MiB/s|NA")
        assert e.percent == 0.0

    def test_never_exceeds_one(self):
        e = yw.parse_progress(f"{yw.TAG_PROGRESS}1200|1000|NA|1MiB/s|00:00")
        assert e.percent == 1.0

    def test_other_lines_ignored(self):
        assert yw.parse_progress("[download] Destination: x.mp4") is None


class TestParseFile:
    def test_mp4_quality_from_height(self):
        e = yw.parse_file(f"{yw.TAG_FILE}C:\\out\\video.mp4|1080|NA|1920x1080", "mp4")
        assert e.path == Path("C:\\out\\video.mp4")
        assert e.quality == "1080p"

    def test_mp3_quality_from_abr(self):
        e = yw.parse_file(f"{yw.TAG_FILE}C:\\out\\a.mp3|NA|192.0|audio only", "mp3")
        assert e.quality == "192 kbps"

    def test_audio_only_resolution_not_used_as_quality(self):
        e = yw.parse_file(f"{yw.TAG_FILE}C:\\out\\a.mp4|NA|NA|audio only", "mp4")
        assert e.quality == ""

    def test_falls_back_to_resolution(self):
        e = yw.parse_file(f"{yw.TAG_FILE}C:\\out\\v.mp4|NA|NA|1280x720", "mp4")
        assert e.quality == "1280x720"

    def test_other_lines_ignored(self):
        assert yw.parse_file("[Merger] Merging formats into ...", "mp4") is None
