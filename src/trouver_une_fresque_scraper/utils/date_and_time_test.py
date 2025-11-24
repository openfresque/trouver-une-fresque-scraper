from datetime import datetime
import logging
from attrs import define


from trouver_une_fresque_scraper.utils import date_and_time


def run_get_dates_tests():
    # tuple fields:
    # 1. Test case name or ID
    # 2. Input date string
    # 3. Expected output start datetime
    # 4. Expected output end datetime
    test_cases = [
        (
            "BilletWeb: one hour",
            "Thu Oct 19, 2023 from 01:00 PM to 02:00 PM",
            datetime(2023, 10, 19, 13, 0),
            datetime(2023, 10, 19, 14, 0),
        ),
        (
            "BilletWeb: multiple months",
            "Thu Oct 19, 2023 at 01:00 PM to Sat Feb 24, 2024 at 02:00 PM",
            datetime(2023, 10, 19, 13, 0),
            datetime(2024, 2, 24, 14, 0),
        ),
        (
            "BilletWeb: single date and time",
            "March 7, 2025 at 10:00 AM",
            datetime(2025, 3, 7, 10, 0),
            datetime(2025, 3, 7, 13, 0),
        ),
        (
            "EventBrite",
            "ven. 11 avr. 2025 14:00 - 17:30 CEST",
            datetime(2025, 4, 11, 14, 0),
            datetime(2025, 4, 11, 17, 30),
        ),
        (
            "FdC French",
            "16 mai 2025, de 18h30 à 21h30 (heure de Paris)",
            datetime(2025, 5, 16, 18, 30),
            datetime(2025, 5, 16, 21, 30),
        ),
        (
            "FdC English: June 3",
            "June 03, 2025, from 05:30pm to 09:30pm (Paris time)",
            datetime(2025, 6, 3, 17, 30),
            datetime(2025, 6, 3, 21, 30),
        ),
        (
            "FdC English: October 28",
            "October 28, 2025, from 09:00am to 12:00pm (Zürich time)",
            datetime(2025, 10, 28, 9, 0),
            datetime(2025, 10, 28, 12, 0),
        ),
        (
            "FEC",
            "03 mars 2025, 14:00 – 17:00 UTC+1",
            datetime(2025, 3, 3, 14, 0),
            datetime(2025, 3, 3, 17, 0),
        ),
        (
            "Glide",
            "mercredi 12 février 2025 de 19h00 à 22h00",
            datetime(2025, 2, 12, 19, 0),
            datetime(2025, 2, 12, 22, 0),
        ),
        (
            "HelloAsso",
            "Le 12 février 2025, de 18h à 20h",
            datetime(2025, 2, 12, 18, 0),
            datetime(2025, 2, 12, 20, 0),
        ),
    ]
    for test_case in test_cases:
        logging.info(f"Running {test_case[0]}")
        actual_start_time, actual_end_time = date_and_time.get_dates(test_case[1])
        if actual_start_time != test_case[2]:
            logging.error(f"{test_case[0]}: expected {test_case[2]} but got {actual_start_time}")
        if actual_end_time != test_case[3]:
            logging.error(f"{test_case[0]}: expected {test_case[3]} but got {actual_end_time}")


@define
class MockWebDriverElement:
    text: str
    dt: str | None

    def get_attribute(self, ignored: str) -> str | None:
        return self.dt


def run_get_dates_from_element_tests():
    # tuple fields:
    # 1. Test case name or ID
    # 2. Input date string
    # 3. Expected output start datetime
    # 4. Expected output end datetime
    test_cases = [
        (
            "BilletWeb: no datetime, fallback on text parsing",
            None,
            "Thu Oct 19, 2023 from 01:00 PM to 02:00 PM",
            datetime(2023, 10, 19, 13, 0),
            datetime(2023, 10, 19, 14, 0),
        ),
        (
            "EventBrite: morning",
            "2025-12-05",
            "déc. 5 de 8am à 11am UTC",
            datetime(2025, 12, 5, 8, 0),
            datetime(2025, 12, 5, 11, 0),
        ),
        (
            "EventBrite: evening",
            "2025-12-12",
            "déc. 12 de 6pm à 9pm UTC+1",
            datetime(2025, 12, 12, 18, 0),
            datetime(2025, 12, 12, 21, 0),
        ),
        (
            "EventBrite: afternoon in German",
            "2024-12-16",
            "Dez. 16 von 5nachm. bis 8nachm. UTC",
            datetime(2024, 12, 16, 17, 0),
            datetime(2024, 12, 16, 20, 0),
        ),
        (
            "EventBrite: afternoon with minutes in German",
            "2024-12-03",
            "Dez. 3 von 5:30nachm. bis 8:30nachm. MEZ",
            datetime(2024, 12, 3, 17, 30),
            datetime(2024, 12, 3, 20, 30),
        ),
        (
            "EventBrite: PM adds 12 to the hours only from 1 PM onwards",
            "2025-12-14",
            "déc. 14 de 9:30am à 12:30pm UTC+1",
            datetime(2025, 12, 14, 9, 30),
            datetime(2025, 12, 14, 12, 30),
        ),
        (
            "EventBrite: start and end minutes differ",
            "2026-01-21",
            "janv. 21 de 9am à 12:30pm UTC+1",
            datetime(2026, 1, 21, 9, 0),
            datetime(2026, 1, 21, 12, 30),
        ),
    ]
    for test_case in test_cases:
        logging.info(f"Running {test_case[0]}")
        actual_start_time, actual_end_time = date_and_time.get_dates_from_element(
            MockWebDriverElement(dt=test_case[1], text=test_case[2])
        )
        if actual_start_time != test_case[3]:
            logging.error(f"{test_case[0]}: expected {test_case[3]} but got {actual_start_time}")
        if actual_end_time != test_case[4]:
            logging.error(f"{test_case[0]}: expected {test_case[4]} but got {actual_end_time}")


def run_tests():
    run_get_dates_tests()
    run_get_dates_from_element_tests()
