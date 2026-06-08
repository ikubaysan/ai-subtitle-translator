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
    translated_srt_path = f"{base}.{translate_to_language}.srt"

    if os.path.exists(translated_srt_path):
        logger.info(f"Skipping '{video_path}' because '{translated_srt_path}' already exists.")
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

    logger.info(f"Translating '{eng_srt_path}' to '{translated_srt_path}'.")
    Translation.translate_srt(
        input_srt_filepath=eng_srt_path,
        output_srt_filepath=translated_srt_path,
        translate_to_language=translate_to_language,
        google_ai_client=google_api_client
    )
    logger.info(f"Japanese translation completed for '{video_path}'.")



def translate_existing_srt(
        srt_path: str,
        translate_to_language: str,
        google_api_client: GoogleAIAPIClient):
    """
    Translate an existing SRT file.

    Example:
        movie.srt
            -> movie.ja.srt
    """

    base, _ = os.path.splitext(srt_path)
    translated_srt = f"{base}.{translate_to_language}.srt"

    if os.path.exists(translated_srt):
        logger.info(
            f"Skipping '{srt_path}' because '{translated_srt}' already exists."
        )
        return

    logger.info(
        f"Translating '{srt_path}' to '{translated_srt}'."
    )

    Translation.translate_srt(
        input_srt_filepath=srt_path,
        output_srt_filepath=translated_srt,
        translate_to_language=translate_to_language,
        google_ai_client=google_api_client
    )



def gather_files_to_process(
        input_path: str,
        recursive: bool):
    """
    Returns two lists:

        video_files
        srt_files

    Supported:
        - directory
        - single video file
        - single srt file
    """

    video_files = []
    srt_files = []

    if not os.path.exists(input_path):
        raise FileNotFoundError(input_path)

    #
    # Single file
    #
    if os.path.isfile(input_path):

        lower = input_path.lower()

        if lower.endswith((".mp4", ".mkv")):
            video_files.append(input_path)

        elif lower.endswith(".srt"):
            srt_files.append(input_path)

        return video_files, srt_files

    #
    # Directory
    #
    if recursive:

        for dirpath, _, filenames in os.walk(input_path):

            for filename in filenames:

                full_path = os.path.join(dirpath, filename)

                lower = filename.lower()

                if lower.endswith((".mp4", ".mkv")):
                    video_files.append(full_path)

                elif lower.endswith(".srt"):
                    srt_files.append(full_path)

    else:

        for filename in os.listdir(input_path):

            full_path = os.path.join(input_path, filename)

            if not os.path.isfile(full_path):
                continue

            lower = filename.lower()

            if lower.endswith((".mp4", ".mkv")):
                video_files.append(full_path)

            elif lower.endswith(".srt"):
                srt_files.append(full_path)

    return video_files, srt_files


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Translate subtitles from videos or SRT files."
    )

    # Path can be:
    # - A directory
    # - A single video file
    # - A single SRT file
    parser.add_argument(
        "input_path",
        nargs="?",
        default=None,
        help="Directory, video file, or SRT file to process."
    )

    parser.add_argument(
        "--input-path",
        dest="input_path",
        help="Directory, video file, or SRT file to process."
    )

    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively scan subdirectories when input is a directory."
    )

    # Allow passing the root directory either:
    # 1. As a positional argument: `python script.py /path/to/videos`
    # 2. As an optional named argument: `python script.py --root-directory /path/to/videos`
    parser.add_argument("root_directory", nargs="?", default=None, help="Root directory to scan for video files.")
    parser.add_argument("--root-directory", dest="root_directory", help="(Optional) Specify root directory for videos.")

    args = parser.parse_args()

    if not args.input_path:
        parser.print_help()
        exit(1)

    input_path = args.input_path

    # Load config
    config = Config('config.ini')

    # Create Google API client
    google_api_client = GoogleAIAPIClient(
        api_key=config.google_ai_api_key,
        model_name=config.google_ai_model_name
    )

    video_files, srt_files = gather_files_to_process(
        input_path=input_path,
        recursive=args.recursive
    )

    logger.info("")
    logger.info("========== FILES TO PROCESS ==========")

    if video_files:

        logger.info("")
        logger.info("Video files (%d):", len(video_files))

        for file_path in video_files:
            logger.info("  %s", file_path)

    if srt_files:

        logger.info("")
        logger.info("SRT files (%d):", len(srt_files))

        for file_path in srt_files:
            logger.info("  %s", file_path)

    logger.info("")
    logger.info(
        "Total files to process: %d",
        len(video_files) + len(srt_files)
    )
    logger.info("======================================")
    logger.info("")

    #
    # Process videos
    #
    for video_path in video_files:
        ensure_subtitles_for_video(
            video_path=video_path,
            translate_to_language=config.translate_to_language,
            delete_pgs_files=config.delete_pgs_files,
            google_api_client=google_api_client
        )

    #
    # Process standalone SRT files
    #
    for srt_path in srt_files:
        translate_existing_srt(
            srt_path=srt_path,
            translate_to_language=config.translate_to_language,
            google_api_client=google_api_client
        )
