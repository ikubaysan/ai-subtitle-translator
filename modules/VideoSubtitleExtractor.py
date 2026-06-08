import json
import subprocess
from pathlib import Path
from typing import Optional, Tuple


class FFmpegNotFoundError(Exception):
    """Exception raised when FFmpeg is not found in PATH."""


class VideoSubtitleExtractor:
    """
    Extract subtitles (SRT/PGS) from a video file using FFmpeg/FFprobe.

    Behavior:
      - Picks the "best" subtitle stream:
          * prefer English ("eng"/"en")
          * prefer non-SDH over SDH (based on title tag)
          * prefer SubRip (srt) over other codecs
          * prefer streams marked default
          * as a final tie-breaker, prefer longer duration if available
      - Stream-copies the selected subtitle without re-encoding (-c:s copy)
      - Writes .extracted.srt if codec is subrip; otherwise .extracted.sup for PGS
    """

    def __init__(self, video_path: str):
        self.video_path = Path(video_path).resolve()
        self.check_binaries()

    # ---------------------------
    # Environment checks
    # ---------------------------
    def check_binaries(self) -> None:
        """Checks if FFmpeg/FFprobe are available in PATH."""
        try:
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            subprocess.run(["ffprobe", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except FileNotFoundError:
            raise FFmpegNotFoundError("FFmpeg/FFprobe are not installed or not found in PATH.")

    # ---------------------------
    # FFprobe helpers
    # ---------------------------
    def _probe_streams(self) -> dict:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-print_format", "json",
            "-show_entries",
            (
                "format=duration:"
                "stream=index,codec_name,codec_type,codec_tag_string,duration,avg_frame_rate,"
                "start_time,disposition:stream_tags=language,title"
            ),
            str(self.video_path),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffprobe failed:\n{proc.stderr.strip()}")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse ffprobe JSON: {e}\nRaw:\n{proc.stdout[:5000]}")

    @staticmethod
    def _score_subtitle_stream(st: dict) -> Tuple[int, float]:
        """
        Return (score, duration_seconds) for ranking.
        Higher score wins; duration used as secondary tiebreaker.
        """
        codec = (st.get("codec_name") or "").lower()
        tags = st.get("tags") or {}
        disp = st.get("disposition") or {}
        lang = (tags.get("language") or "").lower()
        title = (tags.get("title") or "").lower()

        # Parse duration if present (sometimes missing on subs)
        dur_s = 0.0
        try:
            dur_s = float(st.get("duration") or 0.0)
        except (TypeError, ValueError):
            dur_s = 0.0

        score = 0

        # Prefer English language
        if lang in ("eng", "en"):
            score += 100

        # Prefer non-SDH (titles often contain "SDH" or similar)
        if "sdh" not in title:
            score += 10

        # Prefer SubRip over others (e.g., hdmv_pgs_subtitle)
        if codec == "subrip":
            score += 5

        # Prefer streams flagged as default
        if disp.get("default", 0) == 1:
            score += 2

        return score, dur_s

    def _pick_best_sub_stream(self, probe_data: dict) -> Optional[Tuple[int, str]]:
        """
        Returns (stream_index, codec_name) for the best subtitle stream, or None if none exist.
        """
        best = None  # (score, duration, index, codec)
        for st in probe_data.get("streams", []):
            if st.get("codec_type") != "subtitle":
                continue
            idx = st.get("index")
            codec = (st.get("codec_name") or "").lower()
            score, dur_s = self._score_subtitle_stream(st)

            candidate = (score, dur_s, idx, codec)
            if best is None or candidate > best:
                best = candidate

        if best is None:
            return None
        _, _, idx, codec = best
        return idx, codec

    # ---------------------------
    # Public API
    # ---------------------------
    def detect_subtitles(self) -> Optional[str]:
        """
        Backwards-compatibility helper:
        Returns 'srt' if any SubRip exists,
        'pgs' if only PGS exists,
        None if no subtitle streams.
        """
        try:
            probe = self._probe_streams()
        except Exception as e:
            print(f"ffprobe error while detecting subtitles: {e}")
            return None

        found_pgs = False
        found_srt = False
        for st in probe.get("streams", []):
            if st.get("codec_type") != "subtitle":
                continue
            codec = (st.get("codec_name") or "").lower()
            if codec == "subrip":
                found_srt = True
            if codec in ("hdmv_pgs_subtitle", "pgs"):
                found_pgs = True

        if found_srt:
            return "srt"
        if found_pgs:
            return "pgs"
        return None

    def extract_subtitles(self) -> Optional[Path]:
        """
        Extracts the best subtitle stream:
          - Chooses best subtitle stream by heuristic
          - Uses '-c:s copy' (no re-encoding)
          - Suffix: .extracted.srt for SubRip, else .extracted.sup for PGS/others
        Returns the Path to the extracted file, or None on failure.
        """
        try:
            probe = self._probe_streams()
        except Exception as e:
            print(f"Failed to probe streams for {self.video_path.name}: {e}")
            return None

        sel = self._pick_best_sub_stream(probe)
        if not sel:
            print(f"No subtitles found in {self.video_path.name}")
            return None

        stream_idx, codec = sel
        # Build a -map selector from absolute stream index -> use program:stream syntax via -map 0:s:m?
        # Easiest: use "-map 0:s:<N>" where N is the Nth subtitle stream, but we have absolute index.
        # We'll convert absolute index to "N among subtitles":
        sub_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "subtitle"]
        # Map absolute index -> ordinal among subtitle streams
        sub_index_map = {s["index"]: i for i, s in enumerate(sub_streams)}
        ord_within_subs = sub_index_map.get(stream_idx, 0)  # fallback to first subtitle stream

        # Choose output suffix
        is_subrip = (codec == "subrip")
        out_suffix = ".extracted.srt" if is_subrip else ".extracted.sup"
        output_file = self.video_path.with_suffix(out_suffix)

        map_selector = f"0:s:{ord_within_subs}"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(self.video_path),
            "-map", map_selector,
            "-c:s", "copy",
            str(output_file),
        ]

        print(f"Extracting subtitles from: {self.video_path}")
        print(f"  Selected stream: absolute index={stream_idx}, codec={codec}, map={map_selector}")
        print(f"  Command: {cmd}")

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            print(f"Failed to extract subtitles from {self.video_path}\nError:\n{proc.stderr.strip()}")
            return None

        print(f"Success: Extracted subtitles to {output_file}")
        return output_file


if __name__ == "__main__":
    # Simple manual test
    video_file = "path/to/video.mkv"  # Replace with actual video path
    extractor = VideoSubtitleExtractor(video_file)
    extractor.extract_subtitles()
