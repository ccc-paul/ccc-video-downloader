"""视频下载器 —— 从 CCC Live Studio 剥离出来的单功能工具.

只保留 YouTube 视频下载, 给同事在自己电脑上用。
应用数据 (配置 / 历史 / 日志) 存在 %APPDATA%\\VideoDownloader\\。
"""
__version__ = "1.1.3"

# 产品名 / 数据目录名. 与主线的 CCCLiveStudio 分开, 两个程序可以并存互不干扰。
APP_NAME = "视频下载器"
APP_FOLDER = "VideoDownloader"
