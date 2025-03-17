from typing import List, Dict, Type, Generator
from modules.SupToSrtConverter.Errors import InvalidSegmentError
from collections import namedtuple



PDS, ODS, PCS, WDS, END = (0x14, 0x15, 0x16, 0x17, 0x80)
# Named tuple for static PDS palettes
Palette = namedtuple("Palette", "Y Cr Cb Alpha")


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


class ObjectDefinitionSegment(BaseSegment):
    """Handles Object Definition Segment (ODS), which contains run-length encoded image data."""

    def __init__(self, bytes_: bytes) -> None:
        super().__init__(bytes_)
        self.object_id = int(self.data[0:2].hex(), base=16)
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







SEGMENT_TYPE: Dict[int, Type[BaseSegment]] = {
    PDS: PaletteDefinitionSegment,
    ODS: ObjectDefinitionSegment,
    PCS: PresentationCompositionSegment,
    WDS: WindowDefinitionSegment,
    END: EndSegment
}
