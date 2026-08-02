# CONTENTS OF modules/Translation.py

from modules.GoogleAIAPIClient import GoogleAIAPIClient
import json
import re
import srt
from babel import Locale
import logging

logger = logging.getLogger(__name__)


class Translation:
    # ------------------------------------------------------------------
    # Parsing / composing helpers (thin wrappers around the `srt` lib so
    # callers don't need to import it directly)
    # ------------------------------------------------------------------
    @staticmethod
    def parse_srt(srt_text: str) -> list:
        """Parses raw SRT text into a list of srt.Subtitle objects."""
        return list(srt.parse(srt_text))

    @staticmethod
    def compose_srt(subtitles: list) -> str:
        """
        Reconstructs SRT text from a list of srt.Subtitle objects.
        reindex=False keeps the original subtitle numbers exactly as parsed,
        since we never want the AI (or this step) to renumber entries.
        """
        return srt.compose(subtitles, reindex=False)

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------
    @staticmethod
    def _chunk_subtitles(subtitles: list, chunk_size: int):
        """Yields successive chunk_size-sized slices of the subtitle list."""
        if not chunk_size or chunk_size <= 0:
            yield subtitles
            return
        for i in range(0, len(subtitles), chunk_size):
            yield subtitles[i:i + chunk_size]

    # ------------------------------------------------------------------
    # Prompt building / response parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _build_translation_prompt(chunk: list, translate_to_language: str) -> str:
        payload = [{"id": sub.index, "text": sub.content} for sub in chunk]
        return (
            f"Translate the \"text\" field of each object below from English to {translate_to_language}. "
            "Do not change, translate, reorder, add, or remove the \"id\" field or any object. "
            "Preserve any inline formatting tags (like <i>, <b>) in their original positions where sensible. "
            "Preserve line breaks within a text field using \\n. "
            "Return ONLY a valid JSON array with the same objects, each containing \"id\" and \"text\" "
            "(the translated text). No commentary, no markdown, no code fences — JSON only.\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    @staticmethod
    def _parse_translation_response(response_text: str) -> dict:
        """
        Extracts a JSON array from the model's response and returns
        {id: translated_text}. Tolerates markdown code fences and stray
        text before/after the JSON array.
        """
        text = response_text.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        start = text.find('[')
        end = text.rfind(']')
        if start == -1 or end == -1 or end < start:
            raise ValueError("No JSON array found in translation response.")

        json_str = text[start:end + 1]
        data = json.loads(json_str)

        result = {}
        for item in data:
            if not isinstance(item, dict) or "id" not in item or "text" not in item:
                continue
            result[int(item["id"])] = item["text"]
        return result

    # ------------------------------------------------------------------
    # Core translation logic (operates on already-parsed subtitles)
    # ------------------------------------------------------------------
    @staticmethod
    def translate_subtitles(subtitles: list,
                            translate_to_language: str,
                            google_ai_client: GoogleAIAPIClient,
                            split_at: int = 100,
                            progress_callback=None) -> None:
        """
        Translates the .content of each srt.Subtitle in `subtitles`, IN PLACE.
        Timestamps and indices are never sent to the AI and are therefore
        never at risk of being altered.
        :param progress_callback: optional callable(chunk_num, total_chunks)
            invoked after each chunk finishes.
        """
        chunks = list(Translation._chunk_subtitles(subtitles, split_at))
        total_chunks = len(chunks)

        for i, chunk in enumerate(chunks):
            translations = Translation._translate_chunk_with_retry(
                chunk, translate_to_language, google_ai_client
            )
            for sub in chunk:
                if sub.index in translations:
                    sub.content = translations[sub.index]
                else:
                    logger.warning(
                        f"No translation returned for subtitle #{sub.index}; keeping original text."
                    )
            logger.info(f"Translated chunk {i + 1}/{total_chunks} ({len(chunk)} subtitles)")
            if progress_callback:
                progress_callback(i + 1, total_chunks)

    @staticmethod
    def _translate_chunk_with_retry(chunk: list,
                                    translate_to_language: str,
                                    google_ai_client: GoogleAIAPIClient,
                                    max_attempts: int = 3) -> dict:
        """
        Sends a chunk of subtitles for translation and returns {id: translated_text}.
        Retries the whole chunk if the JSON response can't be parsed or is
        missing entries. If it still fails and the chunk has more than one
        subtitle, falls back to translating each subtitle individually so a
        single malformed response doesn't blank out the whole chunk.
        """
        prompt = Translation._build_translation_prompt(chunk, translate_to_language)

        for attempt in range(1, max_attempts + 1):
            try:
                response_text = google_ai_client.send_prompt(prompt)
                translations = Translation._parse_translation_response(response_text)
                missing = [sub.index for sub in chunk if sub.index not in translations]
                if missing and attempt < max_attempts:
                    logger.warning(f"Chunk translation missing ids {missing} on attempt {attempt}; retrying.")
                    continue
                return translations
            except Exception as e:
                logger.warning(f"Failed to parse translation response on attempt {attempt}/{max_attempts}: {e}")

        if len(chunk) > 1:
            logger.warning(f"Falling back to per-subtitle translation for {len(chunk)} subtitles.")
            translations = {}
            for sub in chunk:
                single = Translation._translate_chunk_with_retry(
                    [sub], translate_to_language, google_ai_client, max_attempts=2
                )
                translations.update(single)
            return translations

        logger.error(f"Failed to translate subtitle #{chunk[0].index} after {max_attempts} attempts.")
        return {}

    # ------------------------------------------------------------------
    # File-based convenience wrapper (used by main.py / CLI)
    # ------------------------------------------------------------------
    @staticmethod
    def translate_srt(input_srt_filepath: str,
                      output_srt_filepath: str,
                      translate_to_language: str,
                      google_ai_client: GoogleAIAPIClient,
                      split_at: int = 100,
                      progress_callback=None) -> None:
        """
        Translates an SRT file, preserving the original timestamps and
        subtitle numbering exactly. Only the subtitle *text* is sent to the
        AI for translation; the SRT structure is parsed and reconstructed
        locally, so the AI cannot corrupt timestamps, numbering, or blank-line
        formatting.
        """
        with open(input_srt_filepath, 'r', encoding='utf-8') as f:
            srt_text = f.read()

        subtitles = Translation.parse_srt(srt_text)

        Translation.translate_subtitles(
            subtitles,
            translate_to_language,
            google_ai_client,
            split_at=split_at,
            progress_callback=progress_callback,
        )

        translated_srt_text = Translation.compose_srt(subtitles)
        with open(output_srt_filepath, 'w', encoding='utf-8') as f:
            f.write(translated_srt_text)
        logger.info(f"Saved translated SRT file: {output_srt_filepath}")

    @staticmethod
    def is_valid_language_code(code):
        try:
            Locale.parse(code, sep="_")
            return True
        except ValueError:
            return False