import os
import subprocess
from pathlib import Path
import cv2
import pytesseract
import numpy as np
from typing import List, Optional

# Hardcoded Tesseract OCR path
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH


class FFmpegNotFoundError(Exception):
    """Exception raised when FFmpeg is not found in PATH."""


class VideoSubtitleExtractor:
    """Class to handle subtitle extraction from videos using FFmpeg and Tesseract OCR."""

    def __init__(self, directory: str = "input"):
        self.base_directory: Path = Path(directory).resolve()
        self.check_ffmpeg()

    def check_ffmpeg(self) -> None:
        """Checks if FFmpeg is available in PATH."""
        try:
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except FileNotFoundError:
            raise FFmpegNotFoundError("FFmpeg is not installed or not found in PATH.")

    def get_video_files(self) -> List[Path]:
        """Recursively retrieves all MKV video files from the directory."""
        return list(self.base_directory.rglob("*.mkv"))

    def list_subtitles(self, video_file: Path) -> Optional[str]:
        """Lists the subtitle streams in the MKV file to determine if SRT or PGS (SUP) exists."""
        command = ["ffprobe", "-i", str(video_file), "-show_streams", "-select_streams", "s", "-loglevel", "error"]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        for line in result.stdout.splitlines():
            if "codec_name=srt" in line:
                return "srt"
            if "codec_name=hdmv_pgs_subtitle" in line:
                return "pgs"

        return None  # No subtitles found

    def extract_srt_subtitles(self, video_file: Path) -> None:
        """Extracts SRT subtitles from the MKV file."""
        abs_video_path = video_file.resolve()
        output_file = abs_video_path.with_suffix(".extracted.srt")

        command = [
            "ffmpeg",
            "-i", str(abs_video_path),
            "-map", "0:s:0",
            "-c:s", "srt",
            str(output_file)
        ]

        print(f"Extracting SRT subtitles from: {abs_video_path}")
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            print(f"Success: Extracted SRT subtitles to {output_file}")
        else:
            print(f"Failed to extract SRT subtitles from {abs_video_path}\nError: {result.stderr}")

    def extract_sup_subtitles(self, video_file: Path) -> Optional[Path]:
        """Extracts PGS (SUP) subtitles from the MKV file."""
        abs_video_path = video_file.resolve()
        output_file = abs_video_path.with_suffix(".extracted.sup")

        command = [
            "ffmpeg",
            "-i", str(abs_video_path),
            "-map", "0:s:0",
            "-c:s", "copy",
            str(output_file)
        ]

        print(f"Extracting SUP subtitles from: {abs_video_path}")
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            print(f"Success: Extracted SUP subtitles to {output_file}")
            return output_file
        else:
            print(f"Failed to extract SUP subtitles from {abs_video_path}\nError: {result.stderr}")
            return None

    def convert_sup_to_srt(self, sup_file: Path) -> None:
        """Converts extracted SUP (PGS) subtitles to SRT using OCR."""
        output_folder = sup_file.parent / f"{sup_file.stem}_images"
        output_folder.mkdir(exist_ok=True)

        print(f"Extracting images from SUP subtitles: {sup_file}")

        # Extract subtitle images with proper settings
        image_pattern = str(output_folder / "frame_%04d.png")
        command = [
            "ffmpeg",
            "-i", str(sup_file),
            "-vsync", "0",
            "-frame_pts", "true",
            "-vf", "format=gray",
            image_pattern
        ]
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # Check if images were actually extracted
        image_files = sorted(output_folder.glob("frame_*.png"))
        if not image_files:
            print(f"Error: No subtitle images extracted from {sup_file}.")
            return

        # OCR processing
        srt_output_file = sup_file.with_suffix(".ocr.srt")
        with open(srt_output_file, "w", encoding="utf-8") as srt_file:
            counter = 1
            for image_file in image_files:
                text = self.ocr_image(image_file)
                if text.strip():
                    srt_file.write(f"{counter}\n00:00:00,000 --> 00:00:01,000\n{text}\n\n")
                    counter += 1

        print(f"Success: Converted SUP subtitles to OCR SRT at {srt_output_file}")

    def ocr_image(self, image_path: Path) -> str:
        """Performs OCR on a subtitle image to extract text."""
        img = cv2.imread(str(image_path))

        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Adaptive thresholding to enhance contrast
        enhanced = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5)

        # Run OCR
        text = pytesseract.image_to_string(enhanced, lang="eng")

        # Debugging: Check if OCR extracted any text
        if not text.strip():
            print(f"Warning: No text detected in {image_path}")

        return text.strip()

    def process_directory(self) -> None:
        """Processes all video files in the directory and extracts subtitles."""
        videos = self.get_video_files()

        if not videos:
            print("No MKV video files found in the directory.")
            return

        for video in videos:
            subtitle_type = self.list_subtitles(video)

            if subtitle_type == "srt":
                self.extract_srt_subtitles(video)
            elif subtitle_type == "pgs":
                sup_file = self.extract_sup_subtitles(video)
                if sup_file:
                    self.convert_sup_to_srt(sup_file)
            else:
                print(f"No subtitles found in {video.name}")


if __name__ == "__main__":
    extractor = VideoSubtitleExtractor("input")
    extractor.process_directory()
