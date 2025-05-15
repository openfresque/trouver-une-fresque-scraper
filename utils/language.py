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
    "Italien": "it",
    "Italian": "it",
    "Spanish": "es",
    "Russian": "ru",
}


def detect_language_code(title, description):
    """
    Returns the language code of the language specified in the title if any, otherwise auto-detects from title and description.
    """
    title_upper = title.upper()
    for language_string, language_code in LANGUAGE_STRINGS.items():
        if language_string.upper() in title_upper:
            return language_code
    language_code = detect(title + description)
    if language_code in LANGUAGE_STRINGS.values():
        return language_code
    logging.warning(f"Unexpected language code: {language_code}.")
    return None


def get_language_code(language_text):
    """
    Returns the ISO 639-1 language code given a human-readable string such as "Français" or "English".
    """
    language_code = LANGUAGE_STRINGS.get(language_text)
    if not language_code:
        raise FreskLanguageNotRecognized(language_text)
    return language_code
