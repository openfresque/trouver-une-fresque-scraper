import logging

from utils.errors import FreskLanguageNotRecognized
from langdetect import detect


LANGUAGE_STRINGS = {
        "Allemand": "de",
        "Anglais": "en",
        "Deutsch": "de",
        "Englisch": "en",
        "English": "en",
        "Französisch": "fr",
        "Français": "fr",
        "Français": "fr",
        "German": "de",
    }


def detect_language_code_from_title_and_description(title, description):
    title_upper = title.upper()
    for language_string, language_code in LANGUAGE_STRINGS.items():
        if language_string.upper() in title_upper:
            return language_code
    return detect(title + description)


def get_language_code(language_text):
    """
    Returns the ISO 639-1 language code given a human-readable string such as "Français" or "English".
    """
    language_code = LANGUAGE_STRINGS.get(language_text)
    if not language_code:
        raise FreskLanguageNotRecognized(language_text)
    return language_code
