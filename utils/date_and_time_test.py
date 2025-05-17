from datetime import datetime
import logging


from utils import date_and_time


def run_tests():
    test_cases = [
        (
            "June 3 English",
            "June 03, 2025, from 05:30pm to 09:30pm (Paris time)",
            datetime(2025, 6, 3, 17, 30),
            datetime(2025, 6, 3, 21, 30),
        ),
        (
            "October 28 English",
            "October 28, 2025, from 09:00am to 12:00pm (Zürich time)",
            datetime(2025, 10, 28, 9, 0),
            datetime(2025, 10, 28, 12, 0),
        ),
    ]
    for test_case in test_cases:
        logging.info(f"Running {test_case[0]}")
        actual_start_time, actual_end_time = date_and_time.get_dates(test_case[1])
        if actual_start_time != test_case[2]:
            logging.error(f"{test_case[0]}: expected {test_case[2]} but got {actual_start_time}")
        if actual_end_time != test_case[3]:
            logging.error(f"{test_case[0]}: expected {test_case[3]} but got {actual_end_time}")
