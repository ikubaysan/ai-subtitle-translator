from google import generativeai as genai


class GoogleAIAPIClient:
    def __init__(self, api_key: str, model_name: str):
        """
        A simplified Google Generative AI API client that can send text prompts.

        :param api_key: Your Google Generative AI API key.
        :param model_name: The name of the PaLM / model to use.
        """
        self.api_key = api_key
        self.model_name = model_name

        # These are optional, shown here to disable safety blocks. Adjust as needed.
        self.safe = [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE",
            }
        ]

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name=model_name)

    def send_prompt(self, prompt: str) -> str:
        """
        Sends a single prompt to the Google Generative AI model and returns the text response.
        """
        messages = [{"role": "user", "content": prompt}]
        response = self.model.generate_content(messages, safety_settings=self.safe)
        return response.text
