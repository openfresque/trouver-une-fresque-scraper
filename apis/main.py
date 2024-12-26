import pandas as pd

from apis.glorieuses import get_glorieuses_data

APIS_FNS = {"hook.eu1.make.com": get_glorieuses_data}


def main(apis):
    records = []

    for sourcek in APIS_FNS:
        for api in apis:
            if sourcek in api["url"]:
                records += APIS_FNS[sourcek](api)

    return pd.DataFrame(records)
