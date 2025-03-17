
from modules.GoogleAIAPIClient import GoogleAIAPIClient
from pysrt import SubRipFile
import os


def translate_srt(input_srt_filepath: str,
                                            output_srt_filepath: str,
                                            google_ai_client: GoogleAIAPIClient) -> None:
    """
    Translates an English SRT file to Japanese with furigana, preserving the SRT structure.
    Saves the result to the specified output file.

    :param srt_filepath: Path to the English SRT file to translate.
    :param output_filepath: Path to save the translated SRT file.
    :param google_ai_client: Instance of GoogleAIAPIClient for translation.
    """
    # Load the SRT file into memory
    with open(input_srt_filepath, 'r', encoding='utf-8') as f:
        english_srt_text = f.read()

    # Create a translation prompt
    # prompt = (
    #     "Please translate the entirety of the following SRT subtitles from English to Japanese. "
    #     "For any kanji, add the furigana in parentheses immediately after the kanji. "
    #     "Preserve the same time stamps, line numbering, and overall SRT structure. "
    #     "Output only the translated SRT (no extra explanations). "
    #     "Here is the SRT:\n\n"
    #     f"{english_srt_text}"
    # )

    prompt = (
        "Please translate the entirety of the following SRT subtitles from English to Japanese. "
        "Preserve the same time stamps, line numbering, and overall SRT structure. "
        "Output only the translated SRT file contents, no additional text."
        "Here is the SRT:\n\n"
        f"{english_srt_text}"
    )

    # Ask the AI to translate
    translated_text = google_ai_client.send_prompt(prompt)

    # Save the translated text to the output file
    with open(output_srt_filepath, 'w', encoding='utf-8') as f:
        f.write(translated_text)

    print(f"Saved translated SRT file: {output_srt_filepath}")