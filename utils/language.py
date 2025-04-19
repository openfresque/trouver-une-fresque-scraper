import logging

from utils.errors import FreskLanguageNotRecognized


def get_language_code(language_text):
    """
    Returns the ISO 639-1 language code given a human-readable string such as "Français" or "English".
    """
    language_codes = {
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
    language_code = language_codes.get(language_text)
    if not language_code:
        raise FreskLanguageNotRecognized(language_text)
    return language_code
