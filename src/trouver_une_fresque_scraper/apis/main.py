import pandas as pd

from trouver_une_fresque_scraper.apis.ics import get_ics_data
from trouver_une_fresque_scraper.apis.glorieuses import get_glorieuses_data
from trouver_une_fresque_scraper.apis.mobilite import get_mobilite_data

APIS_FNS = {
    "hook.eu1.make.com": get_glorieuses_data,
    "calendar.google.com/calendar/ical": get_ics_data,
    "framagenda.org/remote.php/dav": get_ics_data,
    "app.fresquedelamobilite.org": get_mobilite_data,
}


def main(apis):
    records = []

    for sourcek in APIS_FNS:
        for api in apis:
            if sourcek in api["url"]:
                records += APIS_FNS[sourcek](api)

    return pd.DataFrame(records)
