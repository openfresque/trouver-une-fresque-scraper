import logging

from trouver_une_fresque_scraper.apis import ics


def run_tests():
    long_url = "https://www.eventbrite.com/e/2tonnes-world-workshop-in-basel-switzerland-tickets-1116862910029?aff=odcleoeventsincollection&keep_tld=1"
    test_cases = [
        ("text_url", long_url, long_url),
        (
            "html_with_extra text",
            '<html><body>Tickets here: <a href="http://result">registration</a>. Come and have fun!</body></html>',
            "http://result",
        ),
        ("text_and_url", "Lien d'inscription : http://result.org", "http://result.org"),
        (
            "more_text_and_url",
            "Fresque du sol animée en ligne.\nInscription obligatoire https://www.billetweb.fr/fresque-du-sol-en-ligne11\nContact si besoinnoone@nowhere.fr.",
            "https://www.billetweb.fr/fresque-du-sol-en-ligne11",
        ),
    ]
    for test_case in test_cases:
        logging.info(f"Running {test_case[0]}")
        actual = ics.get_ticketing_url_from_description(test_case[1])
        if actual == test_case[2]:
            logging.info("Result matches")
        else:
            logging.error(f"{test_case[0]}: expected {test_case[2]} but got {actual}")
