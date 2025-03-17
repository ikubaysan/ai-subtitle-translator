import os

import numpy as np
import pytesseract
from PIL import Image
from pysrt import SubRipFile, SubRipTime, SubRipItem
from tqdm import tqdm

from modules.SupToSrtConverter.PGSReader import PGSReader
from modules.SupToSrtConverter.Segments import PaletteDefinitionSegment, ObjectDefinitionSegment
from modules.GoogleAIAPIClient import GoogleAIAPIClient

from typing import List


class SupToSrtConverter:
    """Converts a PGS subtitle file (.sup) to an SRT file using OCR, and can also call
       the Google Generative AI client to translate the resulting English SRT file
       into Japanese with furigana in parentheses."""

    def __init__(self, input_file: str, output_file: str) -> None:
        self.input_file = input_file
        self.output_file = output_file
        self.pgs = PGSReader(self.input_file)
        self.srt = SubRipFile()

    @staticmethod
    def read_rle_bytes(rle_data: bytes) -> List[List[int]]:
        """
        Decodes run-length-encoded ODS data into lines of pixel indices.
        Each line ends when we see a zero, followed by another zero (0x00 0x00).
        """
        lines = []
        current_line = []

        i = 0
        length_data = len(rle_data)
        while i < length_data:
            first_byte = rle_data[i]

            if first_byte != 0x00:
                # Single-pixel (value first_byte)
                current_line.append(first_byte)
                i += 1
            else:
                # We have an escape or control sequence
                if i + 1 >= length_data:
                    break
                second_byte = rle_data[i + 1]

                if second_byte == 0x00:
                    # End of line
                    lines.append(current_line)
                    current_line = []
                    i += 2
                elif second_byte < 0x40:
                    # 0x00 nn (nn < 64) => nn times '0'
                    run_length = second_byte
                    current_line.extend([0] * run_length)
                    i += 2
                elif second_byte < 0x80:
                    # 0x00 nn (64 <= nn < 128) => big run of zeros
                    if i + 2 < length_data:
                        run_length = ((second_byte - 0x40) << 8) + rle_data[i + 2]
                        current_line.extend([0] * run_length)
                        i += 3
                    else:
                        break
                elif second_byte < 0xC0:
                    # 0x00 nn (128 <= nn < 192) => run of non-zero
                    run_length = second_byte - 0x80
                    if i + 2 < length_data:
                        color = rle_data[i + 2]
                        current_line.extend([color] * run_length)
                        i += 3
                    else:
                        break
                else:
                    # 0x00 nn (192 <= nn) => big run of non-zero
                    run_length = ((second_byte - 0xC0) << 8) + rle_data[i + 2]
                    if i + 3 < length_data:
                        color = rle_data[i + 3]
                        current_line.extend([color] * run_length)
                        i += 4
                    else:
                        break

        if current_line:
            # Last line may not have been terminated by 00 00
            lines.append(current_line)

        return lines

    def process_ocr(self) -> None:
        """Extracts images from the subtitles, runs OCR, and builds an English SRT file."""
        print("Loading subtitles...")
        allsets = list(self.pgs.iter_displaysets())
        print(f"Running OCR on {len(allsets)} DisplaySets...")

        sub_index = 0
        sub_text = ""
        sub_start = 0

        for ds in tqdm(allsets):
            # We only generate a new image when we see ODS+PDS
            # Then we finalize the SRT block when we see the next set w/o image
            segment_types = [seg.type for seg in ds]

            if "ODS" in segment_types and "PDS" in segment_types:
                # Find the palette definition
                pds = next((seg for seg in ds if isinstance(seg, PaletteDefinitionSegment)), None)
                # Find the object definition (image data)
                ods = next((seg for seg in ds if isinstance(seg, ObjectDefinitionSegment)), None)

                if not pds or not ods:
                    continue

                # Convert ODS data (RLE) -> lines -> array -> image
                img = self.make_image(ods, pds)
                # Run OCR
                sub_text = pytesseract.image_to_string(img).strip()
                # Remember the start time
                sub_start = ods.presentation_timestamp
            else:
                # We finalize a subtitle block: [sub_start .. ds_end], containing sub_text
                start_time = SubRipTime(milliseconds=int(sub_start))
                end_time_ms = int(ds[-1].presentation_timestamp)
                end_time = SubRipTime(milliseconds=end_time_ms)

                if sub_text:
                    self.srt.append(SubRipItem(sub_index, start_time, end_time, sub_text))
                    sub_index += 1

    def make_image(self, ods: ObjectDefinitionSegment, pds: PaletteDefinitionSegment) -> Image.Image:
        """
        1) Decode RLE => 2D list of palette indices
        2) Fit into an array of shape (height, width)
        3) Create an 8-bit 'P' image with a grayscale palette for OCR
        """
        lines = self.read_rle_bytes(ods.img_data)

        # Create a 2D array of shape (ods.height, ods.width) filled with 0
        arr = np.zeros((ods.height, ods.width), dtype=np.uint8)

        for row_idx, line in enumerate(lines):
            if row_idx >= ods.height:
                break
            for col_idx, color_idx in enumerate(line):
                if col_idx < ods.width:
                    arr[row_idx, col_idx] = color_idx

        # Create an 8-bit palette image
        img = Image.fromarray(arr, mode='P')

        # Build a grayscale palette from Y
        palette_list = []
        for pal in pds.palette:
            palette_list.extend([pal.Y, pal.Y, pal.Y])  # R,G,B all = Y

        # Pad or trim to 768 (256*3)
        palette_list = palette_list[:768]
        palette_list += [0] * (768 - len(palette_list))
        img.putpalette(palette_list)

        # Convert "P" to "L" for Tesseract (pure grayscale)
        img = img.convert('L')
        return img

    def save_srt(self) -> None:
        """Saves the generated (English) subtitles to an SRT file."""
        print(f"Saving SRT file: {self.output_file}")
        self.srt.save(self.output_file, encoding='utf-8')

    def translate_srt_to_japanese_with_furigana(self, google_ai_client: GoogleAIAPIClient) -> None:
        """
        Sends the entire English SRT text to the Google Generative AI model,
        asking it to translate to Japanese with furigana in parentheses right after any kanji.
        Saves the result to a new SRT file that indicates it's translated to Japanese.
        """
        # Convert the loaded SubRipFile to raw text
        #english_srt_text = str(self.srt)
        english_srt_text = str(self.srt.data)

        # Create a prompt instructing the AI how to translate and how to handle furigana
        # Adjust the instruction to your preference:
        prompt = (
            "Please translate the following SRT subtitles from English to Japanese. "
            "For any kanji, add the furigana in parentheses immediately after the kanji. "
            "Preserve the same time stamps, line numbering, and overall SRT structure. "
            "Output only the translated SRT (no extra explanations). "
            "Here is the SRT:\n\n"
            f"{english_srt_text}"
        )

        # Ask the model to translate
        translated_text = google_ai_client.send_prompt(prompt)

        # Save to a new SRT file (e.g., Archer.S01E01.ja-furigana.srt)
        base, ext = os.path.splitext(self.output_file)
        translated_srt_filename = base + ".ja-furigana.srt"
        print(f"Saving translated SRT file: {translated_srt_filename}")
        with open(translated_srt_filename, 'w', encoding='utf-8') as f:
            f.write(translated_text)

    def convert(self) -> None:
        """Runs the full OCR-based conversion process (English SRT)."""
        self.process_ocr()
        self.save_srt()
