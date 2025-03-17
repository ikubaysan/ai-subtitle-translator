# ai-subtitle-translator


## Description


Uses Google AI API because it's free.

## Prerequisites
* Python 3 installed
* ffmpeg
* tesseract-ocr https://github.com/tesseract-ocr/tesseract/releases/

## Installation
* Clone this repository
* Create a virtual environment for it
* Install the requirements: `pip install -r requirements.txt`
* Rename `config_sample.ini` to `config.ini` and fill in the required fields
  * Don't have a Google AI API key? Create one here: https://aistudio.google.com/app/apikey
* Run the script: `python main.py`