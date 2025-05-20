import argparse
import json
import logging
import subprocess
import sys
import pandas as pd
import psycopg

from datetime import datetime
from pathlib import Path
from psycopg.conninfo import make_conninfo

from apis import main as main_apis
from scraper import main as main_scraper


def configure_logging(log_file_path, error_log_file_path):
    """
    Configures the logging system to write all levels of messages to both a file and the console,
    and errors to a separate file.

    :param log_file_path: The path to the log file for all levels of messages.
    :param error_log_file_path: The path to the log file for error messages only.
    """
    # Ensure the directories exist
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    error_log_file_path.parent.mkdir(parents=True, exist_ok=True)

    # Create a logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Create a file handler for all levels of messages
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    # Create a stream handler for all levels of messages
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    # Create a file handler for error messages only
    error_file_handler = logging.FileHandler(error_log_file_path)
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    # Add handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.addHandler(error_file_handler)


def is_git_repository_dirty():
    # Check if the repository is dirty
    try:
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError as e:
        logging.error(f"Error checking git status: {e}")
        sys.exit(1)


def get_git_commit_hash():
    # Get the current commit hash
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logging.error(f"Error checking git status: {e}")
        sys.exit(1)


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
    parser.add_argument(
        "--skip-dirty-check",
        action="store_true",
        default=False,
        help="skips checking that the git repository is clean",
    )
    args = parser.parse_args()

    # This scraper should be run from a clean state to ensure reproducibility
    dirty = is_git_repository_dirty()
    if dirty and not args.skip_dirty_check:
        logging.warning("The git repository is dirty. Consider a clean state for reproducibility.")
        user_input = input("Do you want to continue? (y/n): ").strip().lower()
        if user_input != "y":
            logging.error("Operation cancelled.")
            sys.exit(0)

    # Validate the source file
    source_path = Path(f"countries/{args.country}.json")
    try:
        with open(source_path, "r") as file:
            content = file.read()
    except FileNotFoundError:
        logging.info(f"Source file {source_path} does not exist.")
        raise

    # Parse the sources
    scrapers, apis = get_sources(content)

    # Build the results path for this run
    dt = datetime.now()
    scraping_time = dt.strftime("%Y%m%d_%H%M%S")
    results_path = Path(f"results/{args.country}/{scraping_time}")
    results_path.mkdir(parents=True, exist_ok=True)
    commit_hash = get_git_commit_hash()
    with open(f"{results_path}/commit_hash.txt", "w") as file:
        file.write(commit_hash)
        if dirty:
            file.write("\n" + "dirty" + "\n")

    # Logging
    log_path = results_path / Path("log.txt")
    errors_path = results_path / Path("error_log.txt")
    configure_logging(log_path, errors_path)

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
        logging.info("Pushing scraped results into db...")
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

        logging.info("Done")
