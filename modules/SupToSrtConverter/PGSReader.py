from os.path import split as pathsplit
from modules.SupToSrtConverter.Segments import BaseSegment, EndSegment, SEGMENT_TYPE
from typing import List, Dict, Type, Generator


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
