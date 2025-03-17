import subprocess
from pathlib import Path
from typing import Optional


class FFmpegNotFoundError(Exception):
    """Exception raised when FFmpeg is not found in PATH."""


class VideoSubtitleExtractor:
    """Class to extract subtitles (SRT/PGS) from a video file using FFmpeg."""

    def __init__(self, video_path: str):
        self.video_path = Path(video_path).resolve()
        self.check_ffmpeg()

    def check_ffmpeg(self) -> None:
        """Checks if FFmpeg is available in PATH."""
        try:
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except FileNotFoundError:
            raise FFmpegNotFoundError("FFmpeg is not installed or not found in PATH.")

    def detect_subtitles(self) -> Optional[str]:
        """Detects whether the video has SRT or PGS subtitles."""
        command = ["ffprobe", "-i", str(self.video_path), "-show_streams", "-select_streams", "s", "-loglevel", "error"]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        for line in result.stdout.splitlines():
            if "codec_name=srt" in line:
                return "srt"
            if "codec_name=hdmv_pgs_subtitle" in line:
                return "pgs"

        return None  # No subtitles found

    def extract_subtitles(self) -> Optional[Path]:
        """Extracts subtitles (SRT or SUP) from the video."""
        subtitle_type = self.detect_subtitles()
        if not subtitle_type:
            print(f"No subtitles found in {self.video_path.name}")
            return None

        output_file = self.video_path.with_suffix(f".extracted.{subtitle_type}")
        command = [
            "ffmpeg",
            "-i", str(self.video_path),
            "-map", "0:s:0",
            "-c:s", "copy" if subtitle_type == "pgs" else "srt",
            str(output_file)
        ]

        print(f"Extracting {subtitle_type.upper()} subtitles from: {self.video_path}")
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            print(f"Success: Extracted {subtitle_type.upper()} subtitles to {output_file}")
            return output_file
        else:
            print(f"Failed to extract subtitles from {self.video_path}\nError: {result.stderr}")
            return None


if __name__ == "__main__":
    video_file = "path/to/video.mkv"  # Replace with actual video path
    extractor = VideoSubtitleExtractor(video_file)
    extractor.extract_subtitles()
