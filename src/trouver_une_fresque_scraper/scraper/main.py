import pandas as pd

from trouver_une_fresque_scraper.scraper.fdc import get_fdc_data
from trouver_une_fresque_scraper.scraper.billetweb import get_billetweb_data
from trouver_une_fresque_scraper.scraper.eventbrite_new import get_eventbrite_new_data
from trouver_une_fresque_scraper.scraper.glide import get_glide_data
from trouver_une_fresque_scraper.scraper.helloasso import get_helloasso_data

SCRAPER_FNS = {
    "billetweb.fr": get_billetweb_data,
    "climatefresk.org": get_fdc_data,
    "eventbrite.com": get_eventbrite_new_data,
    "eventbrite.fr": get_eventbrite_new_data,
    "fresqueduclimat.org": get_fdc_data,
    "1erdegre.glide.page": get_glide_data,
    "helloasso.com": get_helloasso_data,
}


def main(scrapers, headless=False):
    records = []

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
        records += fn_key(sourcev, headless=headless)

    return pd.DataFrame(records)


if __name__ == "__main__":
    main()
