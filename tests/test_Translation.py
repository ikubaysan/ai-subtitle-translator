from modules.Translation import Translation
from modules.Config import Config
from modules.GoogleAIAPIClient import GoogleAIAPIClient



def test_translate_srt():
    config = Config('../config.ini')
    google_api_client = GoogleAIAPIClient(api_key=config.google_ai_api_key, model_name=config.google_ai_model_name)

    output_file = r"C:\Users\PC\Desktop\misc\coding\repos\my_repos\ai-subtitle-translator\output\archer\Archer.S01E01.srt"

    Translation.translate_srt(
        input_srt_filepath=output_file,
        output_srt_filepath=output_file.replace(".srt", ".ja.srt"),
        translate_to_language=config.translate_to_language,
        google_ai_client=google_api_client)

