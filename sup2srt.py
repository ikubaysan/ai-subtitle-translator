#!/usr/bin/env python3

import os
from os.path import split as pathsplit
import numpy as np
from collections import namedtuple
from typing import List, Dict, Type, Generator
from PIL import Image
import pytesseract
from pysrt import SubRipFile, SubRipItem, SubRipTime
from tqdm import tqdm

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# === Constants ===
PDS, ODS, PCS, WDS, END = (0x14, 0x15, 0x16, 0x17, 0x80)

# Named tuple for static PDS palettes
Palette = namedtuple("Palette", "Y Cr Cb Alpha")


# === Exceptions ===
class InvalidSegmentError(Exception):
    """Raised when a segment does not match PGS specification."""


# === Base Segment Class ===
class BaseSegment:
    SEGMENT_TYPES = {PDS: 'PDS', ODS: 'ODS', PCS: 'PCS', WDS: 'WDS', END: 'END'}

    def __init__(self, bytes_: bytes) -> None:
        if bytes_[:2] != b'PG':
            raise InvalidSegmentError("Invalid segment header")

        self.bytes = bytes_
        self.pts = int(bytes_[2:6].hex(), base=16) / 90
        self.dts = int(bytes_[6:10].hex(), base=16) / 90
        self.type = self.SEGMENT_TYPES.get(bytes_[10], "UNKNOWN")

        self.size = int(bytes_[11:13].hex(), base=16)
        self.data = bytes_[13:]

    def __len__(self) -> int:
        return self.size

    @property
    def presentation_timestamp(self) -> float:
        return self.pts


class PaletteDefinitionSegment(BaseSegment):
    def __init__(self, bytes_: bytes) -> None:
        super().__init__(bytes_)
        self.palette_id = self.data[0]
        self.version = self.data[1]
        self.palette = [Palette(0, 0, 0, 0)] * 256

        body = self.data[2:]
        for idx in range(len(body)//5):
            i = idx * 5
            palette_index = body[i]
            # Y, Cr, Cb, Alpha
            y, cr, cb, alpha = body[i+1], body[i+2], body[i+3], body[i+4]
            self.palette[palette_index] = Palette(y, cr, cb, alpha)


class ObjectDefinitionSegment(BaseSegment):
    """Handles Object Definition Segment (ODS), which contains run-length encoded image data."""

    def __init__(self, bytes_: bytes) -> None:
        super().__init__(bytes_)
        self.object_id = int(self.data[0:2].hex(), base=16)
        # self.version = self.data[2]  # Not always used
        self.width = int(self.data[7:9].hex(), base=16)
        self.height = int(self.data[9:11].hex(), base=16)
        # The rest is RLE-compressed image data
        self.img_data = self.data[11:]


class PresentationCompositionSegment(BaseSegment):
    """Handles the Presentation Composition Segment (PCS)."""
    def __init__(self, bytes_: bytes) -> None:
        super().__init__(bytes_)


class WindowDefinitionSegment(BaseSegment):
    """Handles the Window Definition Segment (WDS)."""
    def __init__(self, bytes_: bytes) -> None:
        super().__init__(bytes_)


class EndSegment(BaseSegment):
    @property
    def is_end(self) -> bool:
        return True


# === Segment Type Mapping ===
SEGMENT_TYPE: Dict[int, Type[BaseSegment]] = {
    PDS: PaletteDefinitionSegment,
    ODS: ObjectDefinitionSegment,
    PCS: PresentationCompositionSegment,
    WDS: WindowDefinitionSegment,
    END: EndSegment
}

# === The RLE decoder ===
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
            second_byte = rle_data[i+1]

            if second_byte == 0x00:
                # End of line
                lines.append(current_line)
                current_line = []
                i += 2
            elif second_byte < 0x40:
                # 0x00 nn (nn < 64) => nn times '0'
                run_length = second_byte
                current_line.extend([0]*run_length)
                i += 2
            elif second_byte < 0x80:
                # 0x00 nn (64 <= nn < 128) => big run of zeros
                if i + 2 < length_data:
                    run_length = ((second_byte - 0x40) << 8) + rle_data[i+2]
                    current_line.extend([0]*run_length)
                    i += 3
                else:
                    break
            elif second_byte < 0xC0:
                # 0x00 nn (128 <= nn < 192) => run of non-zero
                # second_byte - 0x80 => length
                run_length = second_byte - 0x80
                if i + 2 < length_data:
                    color = rle_data[i+2]
                    current_line.extend([color]*run_length)
                    i += 3
                else:
                    break
            else:
                # 0x00 nn (192 <= nn) => big run of non-zero
                run_length = ((second_byte - 0xC0) << 8) + rle_data[i+2]
                if i + 3 < length_data:
                    color = rle_data[i+3]
                    current_line.extend([color]*run_length)
                    i += 4
                else:
                    break

    if current_line:
        # Last line may not have been terminated by 00 00
        lines.append(current_line)

    return lines


# === PGS Reader Class ===
class PGSReader:
    """Reads and processes a .sup file containing PGS subtitles."""

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.filedir, self.filename = pathsplit(filepath)

        with open(filepath, 'rb') as f:
            self.bytes = f.read()

    def _parse_segment(self, bytes_: bytes) -> BaseSegment:
        segment_type = bytes_[10]
        if segment_type in SEGMENT_TYPE:
            return SEGMENT_TYPE[segment_type](bytes_)
        else:
            # Fallback if unknown segment type
            return BaseSegment(bytes_)

    def iter_segments(self) -> Generator[BaseSegment, None, None]:
        data = self.bytes[:]
        while data:
            # Segment size is 13 + the 2-byte length
            size = 13 + int(data[11:13].hex(), 16)
            yield self._parse_segment(data[:size])
            data = data[size:]

    def iter_displaysets(self) -> Generator[List[BaseSegment], None, None]:
        ds = []
        for seg in self.iter_segments():
            ds.append(seg)
            if isinstance(seg, EndSegment):
                yield ds
                ds = []


# === Subtitle Extraction Class ===
class SupToSrtConverter:
    """Converts a PGS subtitle file (.sup) to an SRT file using OCR."""

    def __init__(self, input_file: str, output_file: str) -> None:
        self.input_file = input_file
        self.output_file = output_file
        self.pgs = PGSReader(self.input_file)
        self.srt = SubRipFile()

    def process_ocr(self) -> None:
        """Extracts images from the subtitles, runs OCR, and builds an SRT file."""
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
        3) Create an 8-bit 'P' image (or convert to 'L' if you just want grayscale).
        4) (Optional) apply the palette from pds if you want color.
        """
        lines = read_rle_bytes(ods.img_data)

        # We'll create a 2D array of shape (ods.height, ods.width) filled with 0
        # Then copy each line in. If lines or columns are too long, we ignore the overflow.
        arr = np.zeros((ods.height, ods.width), dtype=np.uint8)

        for row_idx, line in enumerate(lines):
            if row_idx >= ods.height:
                break
            for col_idx, color_idx in enumerate(line):
                if col_idx < ods.width:
                    arr[row_idx, col_idx] = color_idx

        # Create an 8-bit palette image
        img = Image.fromarray(arr, mode='P')

        # If you want to apply the real palette from pds, we can build a palette list of 768 bytes (256 * 3).
        # However, for OCR, grayscale is often enough. But let's show how to do it properly:

        # Build a [R,G,B]*256 from the YCbCr data. In PGS, we typically do Y, Cr, Cb.
        # We can do a direct approach or a rough grayscale approach. For better OCR, let's just do a grayscale:
        #   grayscale_value = Y
        # Then set alpha if you want.

        palette_list = []
        for pal in pds.palette:
            # Basic grayscale from Y
            palette_list.extend([pal.Y, pal.Y, pal.Y])  # R,G,B all = Y

        # If the palette_list is shorter than 768, pad it
        palette_list = palette_list[: 768]  # exactly 256*3 if possible
        palette_list += [0] * (768 - len(palette_list))
        img.putpalette(palette_list)

        # You could also create an alpha mask if you want to ignore transparent pixels.
        # For basic OCR, though, the above grayscale is often enough.

        # Convert "P" to "L" so pytesseract sees it as a grayscale image
        img = img.convert('L')
        return img

    def save_srt(self) -> None:
        """Saves the generated subtitles to an SRT file."""
        print(f"Saving SRT file: {self.output_file}")
        self.srt.save(self.output_file, encoding='utf-8')

    def convert(self) -> None:
        """Runs the full conversion process."""
        self.process_ocr()
        self.save_srt()


# === Main Runner ===
if __name__ == "__main__":
    input_file = r"C:\Users\PC\Desktop\misc\coding\repos\my_repos\ai-subtitle-translator\input\archer\Archer.S01E01.extracted.sup"
    output_file = r"C:\Users\PC\Desktop\misc\coding\repos\my_repos\ai-subtitle-translator\output\archer\Archer.S01E01.srt"

    if not os.path.exists(input_file):
        print(f"Error: Input file not found: {input_file}")
        exit(1)

    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    converter = SupToSrtConverter(input_file, output_file)
    converter.convert()
    print("Conversion completed successfully.")
