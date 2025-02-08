import os
import pandas as pd

from scraper.fdc import get_fdc_data
from scraper.fec import get_fec_data
from scraper.billetweb import get_billetweb_data
from scraper.eventbrite import get_eventbrite_data
from scraper.glide import get_glide_data
from scraper.helloasso import get_helloasso_data
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service
from utils.utils import get_config

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
    webdriver = get_config("webdriver")

    if not webdriver:
        webdriver = os.environ["WEBDRIVER_PATH"]

    return webdriver


def main(scrapers, headless=False):
    records = []

    service = Service(executable_path=get_webdriver_executable())
    options = FirefoxOptions()
    options.set_preference("intl.accept_languages", "en-us")
    if headless:
        options.add_argument("-headless")

    sorted_workshops = {}

    # Make sure that we have a scraper available for each fresk entry
    for sourcek in SCRAPER_FNS:
        for workshop in scrapers:
            if sourcek in workshop["url"]:
                # Organize fresks by keys in SCRAPER_FNS
                if sourcek not in sorted_workshops:
                    sorted_workshops[sourcek] = []
                sorted_workshops[sourcek].append(workshop)

    for sourcek, sourcev in sorted_workshops.items():
        records += SCRAPER_FNS[sourcek](sourcev, service=service, options=options)

    return pd.DataFrame(records)


if __name__ == "__main__":
    main()
