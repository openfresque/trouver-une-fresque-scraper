import os
import pandas as pd

from trouver_une_fresque_scraper.scraper.fdc import get_fdc_data
from trouver_une_fresque_scraper.scraper.fec import get_fec_data
from trouver_une_fresque_scraper.scraper.billetweb import get_billetweb_data
from trouver_une_fresque_scraper.scraper.eventbrite import get_eventbrite_data
from trouver_une_fresque_scraper.scraper.glide import get_glide_data
from trouver_une_fresque_scraper.scraper.helloasso import get_helloasso_data
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service
from trouver_une_fresque_scraper.utils.utils import get_config

SCRAPER_FNS = {
    "billetweb.fr": get_billetweb_data,
    "climatefresk.org": get_fdc_data,
    "eventbrite.fr": get_eventbrite_data,
    "fresqueduclimat.org": get_fdc_data,
    "lafresquedeleconomiecirculaire.com": get_fec_data,
    "1erdegre.glide.page": get_glide_data,
    "helloasso.com": get_helloasso_data,
}


def get_webdriver_executable():
    webdriver_path = get_config("webdriver")
    if not webdriver_path and "WEBDRIVER_PATH" in os.environ:
        webdriver_path = os.environ["WEBDRIVER_PATH"]
    return webdriver_path


def main(scrapers, headless=False):
    records = []

    # geckodriver
    service = Service(executable_path=get_webdriver_executable())

    # Firefox
    options = FirefoxOptions()
    if "BROWSER_PATH" in os.environ:
        options.binary_location = os.environ["BROWSER_PATH"]
    options.set_preference("intl.accept_languages", "en-us")

    if headless:
        options.add_argument("-headless")

    sorted_workshops = {}

    # Make sure that we have a scraper available for each fresk entry
    for sourcek, fn_value in SCRAPER_FNS.items():
        for workshop in scrapers:
            if sourcek in workshop["url"]:
                # Organize fresks by values in SCRAPER_FNS
                if fn_value not in sorted_workshops:
                    sorted_workshops[fn_value] = []
                sorted_workshops[fn_value].append(workshop)

    for fn_key, sourcev in sorted_workshops.items():
        records += fn_key(sourcev, service=service, options=options)

    return pd.DataFrame(records)


if __name__ == "__main__":
    main()
