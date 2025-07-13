import logging


from trouver_une_fresque_scraper.utils import language


def run_tests():
    long_url = "https://www.eventbrite.com/e/2tonnes-world-workshop-in-basel-switzerland-tickets-1116862910029?aff=odcleoeventsincollection&keep_tld=1"
    test_cases = [
        (
            "FdB es",
            "CHILE - PROVIDENCIA",
            "El Mural de la Biodiversidad es un taller lúdico y colaborativo que permite sensibilizar sobre la importancia de la biodiversidad y las causas y consecuencias de su erosión. Durante este taller, descubrirás cómo funcionan los ecosistemas, cómo los humanos interactuamos con la biodiversidad y por qué la biodiversidad es crucial para el bienestar del ser humano.",
            "es",
        ),
        (
            "FdB en",
            "Biodiversity Collage (NL) - AMSTERDAM",
            "The Biodiversity Collage is a fun and collaborative workshop that aims to raise awareness about the importance of biodiversity. With a set of cards based on the IPBES reports, you will:",
            "en",
        ),
        (
            "FdB ru",
            "ONLINE BIODIVERSITY COLLAGE WORKSHOP (RU) - with Ivan Ivanovich (CET)",
            "Workshop in Russian Коллаж биоразнообразия — это увлекательный командный воркшоп, который помогает разобраться, почему биоразнообразие критически важно для жизни на Земле и что грозит нашей планете и людям на ней в случае его утраты. В формате совместной работы участники узнают:",
            "ru",
        ),
        (
            "FdN it",
            "ONLINE DIGITAL COLLAGE WORKSHOPS IN ITALIAN - Sessione online con Mario Rossi e Corrado Romano",
            "Il Digital Collage è un workshop ludico e collaborativo. L'obiettivo del workshop è di sensibilizzare e formare i partecipanti sui problemi ambientali e sociali delle tecnologie digitali. Il workshop si propone anche di delineare soluzioni per una maggiore sostenibilità nelle tecnologie digitali e quindi ad aprire discussioni tra i partecipanti sull'argomento.",
            "it",
        ),
        (
            "PlanetC de",
            "Zuerich, Planet C (German)",
            '<a href="https://eventfrog.ch/fr/p/cours-seminaires/autres-cours-seminaires/planet-c-play-again-7281260992926791750.html">Registration</a>',
            "de",
        ),
    ]
    for test_case in test_cases:
        logging.info(f"Running {test_case[0]}")
        actual = language.detect_language_code(test_case[1], test_case[2])
        if actual == test_case[3]:
            logging.info("Result matches")
        else:
            logging.error(f"{test_case[0]}: expected {test_case[3]} but got {actual}")
