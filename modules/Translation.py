from modules.GoogleAIAPIClient import GoogleAIAPIClient
import os
import re


def split_srt_into_chunks(srt_text: str, split_at: int):
    """
    Splits the SRT text into chunks at every `split_at` subtitles.

    :param srt_text: The entire SRT file content.
    :param split_at: The number of subtitles per chunk.
    :return: A list of SRT chunks.
    """
    chunks = []
    current_chunk = []
    last_split_index = 0

    # Split SRT into individual subtitles based on empty lines
    subtitles = srt_text.strip().split("\n\n")

    for i, sub in enumerate(subtitles):
        match = re.match(r"(\d+)\n", sub)
        if match:
            sub_number = int(match.group(1))
            if sub_number >= last_split_index + split_at:
                # Add the current chunk and start a new one
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                last_split_index = sub_number

        current_chunk.append(sub)

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks


def translate_srt(input_srt_filepath: str,
                  output_srt_filepath: str,
                  google_ai_client: GoogleAIAPIClient,
                  split_at: int = 100) -> None:
    """
    Translates an English SRT file to Japanese, preserving the SRT structure.
    If `split_at` is provided, the SRT file is split into chunks for translation.

    :param input_srt_filepath: Path to the English SRT file to translate.
    :param output_srt_filepath: Path to save the translated SRT file.
    :param google_ai_client: Instance of GoogleAIAPIClient for translation.
    :param split_at: Number of subtitles per translation request.
    """
    # Load the SRT file
    with open(input_srt_filepath, 'r', encoding='utf-8') as f:
        english_srt_text = f.read()

    # Split the SRT file into chunks if split_at is set
    srt_chunks = split_srt_into_chunks(english_srt_text, split_at) if split_at else [english_srt_text]

    translated_chunks = []

    #for chunk in srt_chunks:
    for i, chunk in enumerate(srt_chunks):
        prompt = (
            "Please translate the entirety of the following SRT subtitles from English to Japanese. "
            "Preserve the same time stamps, line numbering, and overall SRT structure. "
            "Output only the translated SRT file contents, no additional text.\n\n"
            f"{chunk}"
        )

        # Translate each chunk
        translated_chunk = google_ai_client.send_prompt(prompt)
        translated_chunks.append(translated_chunk)
        print(f"Translated chunk {i + 1}/{len(srt_chunks)} for SRT file: {input_srt_filepath}")

    # Combine all translated chunks
    translated_text = "\n\n".join(translated_chunks)

    # Save the translated text to the output file
    with open(output_srt_filepath, 'w', encoding='utf-8') as f:
        f.write(translated_text)

    print(f"Saved translated SRT file: {output_srt_filepath}")
