#!/usr/bin/env python3
import os
import pytesseract
import logging

from modules.GoogleAIAPIClient import GoogleAIAPIClient
from modules.SupToSrtConverter.SupToSrtConverter import SupToSrtConverter
from modules.Config import Config
from modules.Loggers import configure_console_logger
from modules.Translation import translate_srt
from modules.VideoSubtitleExtractor import VideoSubtitleExtractor

configure_console_logger()
logger = logging.getLogger(__name__)

# Point Tesseract to the proper executable if needed.
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def ensure_subtitles_for_video(video_path: str, google_api_client: GoogleAIAPIClient):
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

    # If Japanese subtitle already exists, skip entirely
    if os.path.exists(jpn_srt_path):
        logger.info(f"Skipping '{video_path}' because '{jpn_srt_path}' already exists.")
        return

    # If no English SRT, attempt to extract from video
    if not os.path.exists(eng_srt_path):
        logger.info(f"No SRT found for '{video_path}'. Attempting extraction...")
        extractor = VideoSubtitleExtractor(video_path)
        extracted_path = extractor.extract_subtitles()  # might be .extracted.srt or .extracted.sup

        if extracted_path is None:
            logger.info(f"No subtitles found or failed to extract for '{video_path}'. Skipping.")
            return

        # If we got a SUP file, convert to SRT
        if extracted_path.suffix.lower() == ".sup":
            logger.info(f"Converting SUP to SRT for '{video_path}'.")
            converter = SupToSrtConverter(str(extracted_path), eng_srt_path)
            converter.convert()
            logger.info("English SRT conversion (from SUP) completed successfully.")
            # Delete the extracted SUP file
            os.remove(str(extracted_path))
            logger.info(f"Deleted extracted SUP file '{extracted_path}'.")
        else:
            # If we extracted SRT directly, rename/move the extracted to .srt if needed
            # (If you'd prefer to keep the .extracted.srt naming, you can skip renaming.)
            os.rename(str(extracted_path), eng_srt_path)
            logger.info(f"Renamed extracted SRT to '{eng_srt_path}'.")

    # At this point, eng_srt_path should exist (unless extraction failed).
    if not os.path.exists(eng_srt_path):
        logger.info(f"Could not find or create an English SRT for '{video_path}'. Skipping translation.")
        return

    # Finally, translate into Japanese, if we haven't done so already
    logger.info(f"Translating '{eng_srt_path}' to '{jpn_srt_path}'.")
    translate_srt(
        input_srt_filepath=eng_srt_path,
        output_srt_filepath=jpn_srt_path,
        google_ai_client=google_api_client
    )
    logger.info(f"Japanese translation completed for '{video_path}'.")


if __name__ == "__main__":
    # Load config
    config = Config('config.ini')

    # Create your Google API client
    google_api_client = GoogleAIAPIClient(
        api_key=config.google_ai_api_key,
        model_name=config.google_ai_model_name
    )

    # Directory to scan recursively
    root_directory = r"C:\Users\PC\Desktop\misc\coding\repos\my_repos\ai-subtitle-translator\input\archer"

    # Walk the directory tree for video files
    for dirpath, dirnames, filenames in os.walk(root_directory):
        for filename in filenames:
            if filename.lower().endswith(('.mp4', '.mkv')):
                full_path = os.path.join(dirpath, filename)
                ensure_subtitles_for_video(full_path, google_api_client)
