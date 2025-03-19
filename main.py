#!/usr/bin/env python3
import os
import pytesseract
import logging
import argparse

from modules.GoogleAIAPIClient import GoogleAIAPIClient
from modules.SupToSrtConverter.SupToSrtConverter import SupToSrtConverter
from modules.Config import Config
from modules.Loggers import configure_console_logger
from modules.Translation import Translation
from modules.VideoSubtitleExtractor import VideoSubtitleExtractor

configure_console_logger()
logger = logging.getLogger(__name__)

# Point Tesseract to the proper executable if needed.
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def ensure_subtitles_for_video(video_path: str,
                               translate_to_language: str,
                               delete_pgs_files: bool,
                               google_api_client: GoogleAIAPIClient):
    """
    Given a path to a video (mp4/mkv), ensure it ends up with:
      - An English SRT (video_path + '.srt')
      - A Japanese SRT (video_path + '.ja.srt')

    Steps:
      1) Check if .ja.srt already exists. If so, skip everything.
      2) Otherwise, check if .srt already exists.
      3) If not, extract subtitles (SRT or SUP) using VideoSubtitleExtractor.
      4) If SUP extracted, convert it to .srt using SupToSrtConverter.
      5) Finally, translate the .srt to .ja.srt (if not already present).
    """
    base, _ = os.path.splitext(video_path)
    eng_srt_path = base + ".srt"
    jpn_srt_path = base + ".ja.srt"

    if os.path.exists(jpn_srt_path):
        logger.info(f"Skipping '{video_path}' because '{jpn_srt_path}' already exists.")
        return

    if not os.path.exists(eng_srt_path):
        logger.info(f"No SRT found for '{video_path}'. Attempting extraction...")
        extractor = VideoSubtitleExtractor(video_path)
        extracted_path = extractor.extract_subtitles()

        if extracted_path is None:
            logger.info(f"No subtitles found or failed to extract for '{video_path}'. Skipping.")
            return

        if extracted_path.suffix.lower() == ".sup":
            logger.info(f"Converting SUP to SRT for '{video_path}'.")
            converter = SupToSrtConverter(str(extracted_path), eng_srt_path)
            converter.convert()
            logger.info("English SRT conversion (from SUP) completed successfully.")
            if delete_pgs_files:
                os.remove(str(extracted_path))
                logger.info(f"Deleted extracted PGS (.sup) file '{extracted_path}'.")
        else:
            os.rename(str(extracted_path), eng_srt_path)
            logger.info(f"Renamed extracted SRT to '{eng_srt_path}'.")

    if not os.path.exists(eng_srt_path):
        logger.info(f"Could not find or create an English SRT for '{video_path}'. Skipping translation.")
        return

    logger.info(f"Translating '{eng_srt_path}' to '{jpn_srt_path}'.")
    Translation.translate_srt(
        input_srt_filepath=eng_srt_path,
        output_srt_filepath=jpn_srt_path,
        translate_to_language=translate_to_language,
        google_ai_client=google_api_client
    )
    logger.info(f"Japanese translation completed for '{video_path}'.")


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Ensure subtitles for all videos in a given directory.")

    # Allow passing the root directory either:
    # 1. As a positional argument: `python script.py /path/to/videos`
    # 2. As an optional named argument: `python script.py --root-directory /path/to/videos`
    parser.add_argument("root_directory", nargs="?", default=None, help="Root directory to scan for video files.")
    parser.add_argument("--root-directory", dest="root_directory", help="(Optional) Specify root directory for videos.")

    args = parser.parse_args()

    # If no directory is provided, print usage and exit
    if not args.root_directory:
        parser.print_help()
        exit(1)

    root_directory = args.root_directory

    # Load config
    config = Config('config.ini')

    # Create Google API client
    google_api_client = GoogleAIAPIClient(
        api_key=config.google_ai_api_key,
        model_name=config.google_ai_model_name
    )

    # Walk the directory tree for video files
    for dirpath, dirnames, filenames in os.walk(root_directory):
        for filename in filenames:
            if filename.lower().endswith(('.mp4', '.mkv')):
                full_path = os.path.join(dirpath, filename)
                ensure_subtitles_for_video(video_path=full_path,
                                           translate_to_language=config.translate_to_language,
                                           delete_pgs_files=config.delete_pgs_files,
                                           google_api_client=google_api_client)
