import argparse
import json
import logging
import pandas as pd
import psycopg

from datetime import datetime
from pathlib import Path
from psycopg.conninfo import make_conninfo

from apis import main as main_apis
from scraper import main as main_scraper


def get_sources(content):
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode JSON: {e}")
        raise
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        raise

    # Validate the data structure
    for d in data:
        if not isinstance(d, dict):
            logging.error(f"Invalid data structure: expected a dictionary, got {type(d).__name__}")
            raise

        required_keys = ["name", "id", "url", "type"]
        for key in required_keys:
            if key not in d:
                logging.error(f"Missing required key '{key}' in data: {d}")
                raise

    scrapers, apis = [], []
    for d in data:
        if d["type"] == "scraper":
            scrapers.append(d)
        elif d["type"] == "api":
            apis.append(d)

    return scrapers, apis


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--country",
        default="fr",
        help="run the scraper for the given json containing data sources",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="run scraping in headless mode",
    )
    parser.add_argument(
        "--push-to-db",
        action="store_true",
        default=False,
        help="push the scraped results to db",
    )
    args = parser.parse_args()

    # Validate the source file
    source_path = Path(f"countries/{args.country}.json")
    try:
        with open(source_path, "r") as file:
            content = file.read()
    except FileNotFoundError:
        print(f"Source file {source_path} does not exist.")
        raise

    # Parse the sources
    scrapers, apis = get_sources(content)

    # Build the results path for this run
    dt = datetime.now()
    scraping_time = dt.strftime("%Y%m%d_%H%M%S")
    results_path = Path(f"results/{args.country}/{scraping_time}")
    results_path.mkdir(parents=True, exist_ok=True)

    # Error logging
    errors_path = results_path / Path(f"error_log.txt")
    logging.basicConfig(
        filename=errors_path,
        level=logging.ERROR,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    # Launch the scraper
    df1 = main_scraper(scrapers, headless=args.headless)
    df2 = main_apis(apis)
    df_merged = pd.concat([df1, df2])

    dt = datetime.now()
    insert_time = dt.strftime("%Y%m%d_%H%M%S")
    with open(results_path / Path(f"events_{insert_time}.json"), "w", encoding="UTF-8") as file:
        df_merged.to_json(file, orient="records", force_ascii=False, indent=2)

    # Push the resulting json file to the database
    if args.push_to_db:
        print("Pushing scraped results into db...")
        credentials = get_config()
        host = credentials["host"]
        port = credentials["port"]
        user = credentials["user"]
        psw = credentials["psw"]
        database = credentials["database"]

        with psycopg.connect(
            make_conninfo(dbname=database, user=user, password=psw, host=host, port=port)
        ) as conn:
            etl(conn, df_merged)

        print("Done")
