#!/usr/bin/env python3
import os
from typing import List
import pytesseract

from modules.GoogleAIAPIClient import GoogleAIAPIClient
from modules.SupToSrtConverter.SupToSrtConverter import SupToSrtConverter
from modules.Config import Config
from modules.Loggers import configure_console_logger
from modules.Translation import translate_srt
import logging

configure_console_logger()
logger = logging.getLogger(__name__)

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# === Main Runner ===
if __name__ == "__main__":
    config = Config('config.ini')

    input_file = r"C:\Users\PC\Desktop\misc\coding\repos\my_repos\ai-subtitle-translator\input\archer\Archer.S01E01.extracted.sup"
    output_file = r"C:\Users\PC\Desktop\misc\coding\repos\my_repos\ai-subtitle-translator\output\archer\Archer.S01E01.srt"

    if not os.path.exists(input_file):
        print(f"Error: Input file not found: {input_file}")
        exit(1)

    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # 1) Convert the PGS SUP file to an English SRT via OCR
    converter = SupToSrtConverter(input_file, output_file)
    converter.convert()
    print("English SRT conversion completed successfully.")

    # 2) Translate the English SRT to Japanese with furigana
    google_api_client = GoogleAIAPIClient(api_key=config.google_ai_api_key, model_name=config.google_ai_model_name)
    translate_srt(
        input_srt_filepath=output_file,
        output_srt_filepath=output_file.replace(".srt", ".ja.srt"),
        google_ai_client=google_api_client)
    print("Japanese translation completed successfully.")
