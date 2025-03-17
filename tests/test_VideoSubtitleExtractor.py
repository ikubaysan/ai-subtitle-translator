from modules.VideoSubtitleExtractor import VideoSubtitleExtractor
import os
import pytest


def test_detect_subtitle_type():
    video_file = r"C:\Users\PC\Desktop\misc\coding\repos\my_repos\ai-subtitle-translator\input\archer\Archer.S02E07.1080p.BluRay.DTS-MA.x264.mkv"
    extractor = VideoSubtitleExtractor(video_file)
    subtitle_type = extractor.detect_subtitles()
    assert subtitle_type == "pgs"