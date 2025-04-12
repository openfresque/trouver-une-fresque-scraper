import json
import argparse
import pandas as pd
import psycopg

from psycopg.conninfo import make_conninfo

from db.etl import etl, insert, truncate
from utils.utils import get_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full-etl",
        action="store_true",
        default=True,
        help="perform the full ETL cycle, including truncating future events",
    )
    parser.add_argument(
        "--truncate-first",
        action="store_true",
        default=False,
        help="truncate db before inserting again",
    )
    parser.add_argument(
        "--input",
        type=str,
        help="input json file to be inserted in db",
        required=True,
    )
    args = parser.parse_args()

    if args.full_etl and args.truncate_first:
        raise Exception

    credentials = get_config()
    host = credentials["host"]
    port = credentials["port"]
    user = credentials["user"]
    psw = credentials["psw"]
    database = credentials["database"]

    with psycopg.connect(
        make_conninfo(dbname=database, user=user, password=psw, host=host, port=port)
    ) as conn:
        input_records = open(args.input, "r")
        input_records = json.loads(input_records.read())
        df = pd.DataFrame.from_dict(pd.json_normalize(input_records), orient="columns")
        print(df)

        if args.full_etl:
            etl(conn, df)
        else:
            if args.truncate_first:
                truncate(conn, "private.events_future")
            insert(conn, df, "private.events_future")
