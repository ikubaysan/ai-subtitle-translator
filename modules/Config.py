import configparser



class Config:
    def __init__(self, config_file_path: str):
        self.config_file_path = config_file_path
        self.config = configparser.ConfigParser()
        self.config.read(self.config_file_path)

        self.google_ai_api_key = self.config.get('google_ai_api', 'api_key')
        self.google_ai_model_name = self.config.get('google_ai_api', 'model_name')

        self.translate_to_language = self.config.get('translation', 'translate_to_language')

        self.delete_pgs_files = self.config.getboolean('files', 'delete_pgs_files')