import re
import traceback
import logging

from datetime import datetime, timedelta
from dateutil.parser import parse

from trouver_une_fresque_scraper.utils.errors import (
    FreskError,
    FreskDateBadFormat,
    FreskDateDifferentTimezone,
)

DEFAULT_DURATION = 3
CURRENT_YEAR = 2026

FRENCH_SHORT_DAYS = {
    "lun": 1,
    "mar": 2,
    "mer": 3,
    "jeu": 4,
    "ven": 5,
    "sam": 6,
    "dim": 7,
}

FRENCH_DAYS = {
    "lundi": 1,
    "mardi": 2,
    "mercredi": 3,
    "jeudi": 4,
    "vendredi": 5,
    "samedi": 6,
    "dimanche": 7,
}

FRENCH_SHORT_MONTHS = {
    "janv": 1,
    "févr": 2,
    "mars": 3,
    "avr": 4,
    "mai": 5,
    "juin": 6,
    "juil": 7,
    "août": 8,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "déc": 12,
}

FRENCH_MONTHS = {
    "janvier": 1,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
}


def get_dates(event_time):
    try:
        # ===================
        # FdC English

        # June 03, 2025, from 05:30pm to 09:30pm (Paris time)
        if match := re.match(
            r"(?P<date>\w+\s\d{2},\s\d{4})"
            r",\sfrom\s"
            r"(?P<start_time>\d{2}:\d{2}[ap]m)"
            r"\sto\s"
            r"(?P<end_time>\d{2}:\d{2}[ap]m)"
            r"\s\(.*\stime\)",
            event_time,
        ):
            event_start_datetime = parse(f"{match.group('date')} {match.group('start_time')}")
            event_end_datetime = parse(f"{match.group('date')} {match.group('end_time')}")
            return event_start_datetime, event_end_datetime

        # ===================
        # Billetweb

        # Thu Oct 19, 2023 from 01:00 PM to 02:00 PM
        if match := re.match(
            r"(?P<date>.*)\s" r"from\s" r"(?P<start_time>.*)\s" r"to\s" r"(?P<end_time>.*)",
            event_time,
        ):
            event_start_datetime = parse(f"{match.group('date')} {match.group('start_time')}")
            event_end_datetime = parse(f"{match.group('date')} {match.group('end_time')}")
            return event_start_datetime, event_end_datetime

        # ===================
        # Billetweb

        # Thu Oct 19, 2023 at 01:00 PM to Sat Feb 24, 2024 at 02:00 PM
        elif match := re.match(
            r"(?P<start_date>.*)\s"
            r"at\s"
            r"(?P<start_time>.*)\s"
            r"to\s"
            r"(?P<end_date>.*)\s"
            r"at\s"
            r"(?P<end_time>.*)",
            event_time,
        ):
            event_start_datetime = parse(f"{match.group('start_date')} {match.group('start_time')}")
            event_end_datetime = parse(f"{match.group('end_date')} {match.group('end_time')}")
            return event_start_datetime, event_end_datetime

        # ===================
        # Billetweb

        # Thu Oct 19, 2023 at 01:00 PM
        # March 7, 2025 at 10:00 AM
        elif match := re.match(r"(?P<date>.*)\s" r"at\s" r"(?P<time>.*)", event_time):
            event_start_datetime = parse(f"{match.group('date')} {match.group('time')}")
            event_end_datetime = event_start_datetime + timedelta(hours=DEFAULT_DURATION)
            return event_start_datetime, event_end_datetime

        # ===================
        # Eventbrite collection modal - calendar style (English)

        # SAT, January 24 9:00 am
        # WED, February 28 6:30 pm
        elif match := re.match(
            r"(?P<day_of_week>\w{3}),\s"
            r"(?P<month>\w+)\s"
            r"(?P<day>\d{1,2})\s"
            r"(?P<start_time>\d{1,2}:\d{2}\s[ap]m)",
            event_time,
        ):
            # Use current year or next year if month has passed
            current_date = datetime.now()
            month_name = match.group("month")
            day = int(match.group("day"))

            # Parse the month name
            temp_date = parse(f"{month_name} {day}")
            year = current_date.year

            # If the parsed month/day is before current date, assume next year
            if temp_date.replace(year=year) < current_date:
                year += 1

            # Parse full start time with inferred year and add default duration for end
            date_str = f"{month_name} {day} {year}"
            event_start_datetime = parse(f"{date_str} {match.group('start_time')}")
            event_end_datetime = event_start_datetime + timedelta(hours=DEFAULT_DURATION)

            return event_start_datetime, event_end_datetime

        # ===================
        # Eventbrite collection modal - calendar style (French)

        # MER., janvier 14 6:30 pm
        # SAM., janvier 17 2:00 pm
        # JEU., janvier 22 6:30 pm
        elif match := re.match(
            rf"(?P<day_of_week>{'|'.join(FRENCH_SHORT_DAYS.keys()).upper()})\.?,?\s"
            rf"(?P<month>{'|'.join(FRENCH_MONTHS.keys())})\s"
            r"(?P<day>\d{1,2})\s"
            r"(?P<start_time>\d{1,2}:\d{2}\s[ap]m)",
            event_time,
            re.IGNORECASE,
        ):
            current_date = datetime.now()
            month_name = match.group("month").lower()
            day = int(match.group("day"))

            # Get month number from French name
            month_num = FRENCH_MONTHS.get(month_name)
            if not month_num:
                raise FreskDateBadFormat(event_time)

            # Determine year
            year = current_date.year
            temp_date = datetime(year, month_num, day)

            # If the date is before current date, assume next year
            if temp_date < current_date:
                year += 1

            # Build date string and parse with time
            date_str = f"{year}-{month_num:02d}-{day:02d}"
            event_start_datetime = parse(f"{date_str} {match.group('start_time')}")
            event_end_datetime = event_start_datetime + timedelta(hours=DEFAULT_DURATION)

            return event_start_datetime, event_end_datetime

        # ===================
        # Eventbrite collection modal - list style (English)

        # Sat, Feb 14 9:00 am - 12:30 pm
        # Mon, Jan 20 6:00 pm - 9:30 pm
        elif match := re.match(
            r"(?P<day_of_week>\w{3}),\s"
            r"(?P<month>\w{3})\s"
            r"(?P<day>\d{1,2})\s"
            r"(?P<start_time>\d{1,2}:\d{2}\s[ap]m)\s"
            r"-\s"
            r"(?P<end_time>\d{1,2}:\d{2}\s[ap]m)",
            event_time,
        ):
            # Use current year or next year if month has passed
            current_date = datetime.now()
            month_abbr = match.group("month")
            day = int(match.group("day"))

            # Parse the month abbreviation
            temp_date = parse(f"{month_abbr} {day}")
            year = current_date.year

            # If the parsed month/day is before current date, assume next year
            if temp_date.replace(year=year) < current_date:
                year += 1

            # Parse full start and end times with inferred year
            date_str = f"{month_abbr} {day} {year}"
            event_start_datetime = parse(f"{date_str} {match.group('start_time')}")
            event_end_datetime = parse(f"{date_str} {match.group('end_time')}")

            return event_start_datetime, event_end_datetime

        # ===================
        # Eventbrite collection modal - list style (French)

        # jeu., févr. 26 6:30 pm - 9:45 pm
        # lun., janv. 20 6:00 pm - 9:30 pm
        elif match := re.match(
            rf"(?P<day_of_week>{'|'.join(FRENCH_SHORT_DAYS.keys())})\.?,?\s"
            rf"(?P<month>{'|'.join(FRENCH_SHORT_MONTHS.keys())})\.?\s"
            r"(?P<day>\d{1,2})\s"
            r"(?P<start_time>\d{1,2}:\d{2}\s[ap]m)\s"
            r"-\s"
            r"(?P<end_time>\d{1,2}:\d{2}\s[ap]m)",
            event_time,
            re.IGNORECASE,
        ):
            current_date = datetime.now()
            month_abbr = match.group("month").lower()
            day = int(match.group("day"))

            # Get month number from French abbreviation
            month_num = FRENCH_SHORT_MONTHS.get(month_abbr)
            if not month_num:
                raise FreskDateBadFormat(event_time)

            # Determine year
            year = current_date.year
            temp_date = datetime(year, month_num, day)

            # If the date is before current date, assume next year
            if temp_date < current_date:
                year += 1

            # Build date string and parse with times
            date_str = f"{year}-{month_num:02d}-{day:02d}"
            event_start_datetime = parse(f"{date_str} {match.group('start_time')}")
            event_end_datetime = parse(f"{date_str} {match.group('end_time')}")

            return event_start_datetime, event_end_datetime

        # ===================
        # Eventbrite

        # ven. 11 avr. 2025 14:00 - 17:30 CEST
        elif match := re.match(
            rf"(?P<day_of_week>{'|'.join(FRENCH_SHORT_DAYS.keys())})\.?\s"
            r"(?P<day>\d{1,2})\s"
            rf"(?P<month>{'|'.join(FRENCH_SHORT_MONTHS.keys())})\.?\s"
            r"(?P<year>\d{4})\s"
            r"(?P<start_time>\d{2}:\d{2})\s"
            r"-\s"
            r"(?P<end_time>\d{2}:\d{2})\s"
            r"(?P<timezone>.*)",
            event_time,
        ):
            event_start_datetime = datetime(
                int(match.group("year")),
                FRENCH_SHORT_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("start_time").split(":")[0]),
                int(match.group("start_time").split(":")[1]),
            )
            event_end_datetime = datetime(
                int(match.group("year")),
                FRENCH_SHORT_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("end_time").split(":")[0]),
                int(match.group("end_time").split(":")[1]),
            )
            return event_start_datetime, event_end_datetime

        # ===================
        # FdC French

        # 16 mai 2025, de 18h30 à 21h30 (heure de Paris)
        elif match := re.match(
            r"(?P<day>\d{1,2})\s"
            rf"(?P<month>{'|'.join(FRENCH_MONTHS.keys())})\s"
            r"(?P<year>\d{4}),\s"
            r"de\s"
            r"(?P<start_time>\d{1,2}h\d{2})\s"
            r"à\s"
            r"(?P<end_time>\d{1,2}h\d{2})",
            event_time,
        ):
            # Construct the datetime objects
            event_start_datetime = datetime(
                int(match.group("year")),
                FRENCH_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("start_time").split("h")[0]),
                int(match.group("start_time").split("h")[1]),
            )
            event_end_datetime = datetime(
                int(match.group("year")),
                FRENCH_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("end_time").split("h")[0]),
                int(match.group("end_time").split("h")[1]),
            )
            return event_start_datetime, event_end_datetime

        # ===================
        # FEC

        # 03 mars 2025, 14:00 – 17:00 UTC+1
        elif match := re.match(
            rf"((?P<day_of_week>{'|'.join(FRENCH_SHORT_DAYS.keys())})\.?\s)?"
            r"(?P<day>\d{1,2})\s"
            rf"(?P<month>{'|'.join(FRENCH_SHORT_MONTHS.keys())})\.?\s"
            r"(?P<year>\d{4})?,\s"
            r"(?P<start_time>\d{2}:\d{2})\s"
            r"–\s"
            r"(?P<end_time>\d{2}:\d{2})"
            r"(\sUTC(?P<timezone>.*))?",
            event_time,
        ):
            timezone = match.group("timezone")
            if timezone and timezone not in ("+1", "+2"):
                raise FreskDateDifferentTimezone(event_time)

            event_start_datetime = datetime(
                int(match.group("year")),
                FRENCH_SHORT_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("start_time").split(":")[0]),
                int(match.group("start_time").split(":")[1]),
            )
            event_end_datetime = datetime(
                int(match.group("year")),
                FRENCH_SHORT_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("end_time").split(":")[0]),
                int(match.group("end_time").split(":")[1]),
            )
            return event_start_datetime, event_end_datetime

        # ===================
        # Glide

        # mercredi 12 février 2025 de 19h00 à 22h00
        elif match := re.match(
            rf"((?P<day_of_week>{'|'.join(FRENCH_DAYS.keys())})\s)?"
            r"(?P<day>\d{1,2})\s"
            rf"(?P<month>{'|'.join(FRENCH_MONTHS)})\s"
            r"(?P<year>\d{4})\s"
            r"de\s"
            r"(?P<start_time>\d{1,2}h\d{2})\s"
            r"à\s"
            r"(?P<end_time>\d{1,2}h\d{2})",
            event_time,
        ):
            event_start_datetime = datetime(
                int(match.group("year")),
                FRENCH_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("start_time").split("h")[0]),
                int(match.group("start_time").split("h")[1]),
            )
            event_end_datetime = datetime(
                int(match.group("year")),
                FRENCH_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("end_time").split("h")[0]),
                int(match.group("end_time").split("h")[1]),
            )
            return event_start_datetime, event_end_datetime

        # ===================
        # HelloAsso

        # Le 12 février 2025, de 18h à 20h
        elif match := re.match(
            r"Le\s"
            r"(?P<day>\d{1,2})\s"
            rf"(?P<month>{'|'.join(FRENCH_MONTHS)})\s"
            r"(?P<year>\d{4}),\s"
            r"de\s"
            r"(?P<start_time>\d{1,2}h\d{0,2})\s"
            r"à\s"
            r"(?P<end_time>\d{1,2}h\d{0,2})",
            event_time,
        ):
            start_parts = match.group("start_time").split("h")
            event_start_datetime = datetime(
                int(match.group("year")),
                FRENCH_MONTHS[match.group("month")],
                int(match.group("day")),
                int(start_parts[0]),
                (int(start_parts[1]) if len(start_parts) > 1 and len(start_parts[1]) else 0),
            )
            end_parts = match.group("end_time").split("h")
            event_end_datetime = datetime(
                int(match.group("year")),
                FRENCH_MONTHS[match.group("month")],
                int(match.group("day")),
                int(end_parts[0]),
                int(end_parts[1]) if len(end_parts) > 1 and len(end_parts[1]) else 0,
            )
            return event_start_datetime, event_end_datetime

        # ===================
        # Eventbrite collection modal - mixed French/English format

        # janv. 24 de 2pm à 5:30pm UTC+1
        # févr. 15 de 9am à 12:30pm UTC+1
        elif match := re.match(
            rf"(?P<month>{'|'.join(FRENCH_SHORT_MONTHS.keys())})\.?\s"
            r"(?P<day>\d{1,2})\s"
            r"de\s"
            r"(?P<start_hour>\d{1,2})(?::(?P<start_minute>\d{2}))?(?P<start_ampm>am|pm)\s"
            r"à\s"
            r"(?P<end_hour>\d{1,2})(?::(?P<end_minute>\d{2}))?(?P<end_ampm>am|pm)"
            r"(\s+UTC(?P<timezone>[+-]?\d+))?",
            event_time,
            re.IGNORECASE,
        ):
            timezone = match.group("timezone")
            if timezone and timezone not in ("+1", "+2", "1", "2"):
                raise FreskDateDifferentTimezone(event_time)

            # Determine year (current year, or next year if the date has passed)
            current_date = datetime.now()
            month_num = FRENCH_SHORT_MONTHS[match.group("month").lower()]
            day = int(match.group("day"))

            year = current_date.year
            temp_date = datetime(year, month_num, day)
            if temp_date < current_date:
                year += 1

            # Parse start time with AM/PM
            start_hour = int(match.group("start_hour"))
            start_minute = int(match.group("start_minute") or 0)
            if match.group("start_ampm").lower() == "pm" and start_hour < 12:
                start_hour += 12
            elif match.group("start_ampm").lower() == "am" and start_hour == 12:
                start_hour = 0

            # Parse end time with AM/PM
            end_hour = int(match.group("end_hour"))
            end_minute = int(match.group("end_minute") or 0)
            if match.group("end_ampm").lower() == "pm" and end_hour < 12:
                end_hour += 12
            elif match.group("end_ampm").lower() == "am" and end_hour == 12:
                end_hour = 0

            event_start_datetime = datetime(year, month_num, day, start_hour, start_minute)
            event_end_datetime = datetime(year, month_num, day, end_hour, end_minute)

            return event_start_datetime, event_end_datetime

        # ===================
        # Eventbrite event-datetime format (French with "du/aux")

        # vendredi, févr. 13, 2026 du 7 pm aux 10 pm CET
        # samedi, janv. 25, 2026 du 9 am aux 12:30 pm CET
        elif match := re.match(
            rf"(?P<day_of_week>{'|'.join(FRENCH_DAYS.keys())}),?\s"
            rf"(?P<month>{'|'.join(FRENCH_SHORT_MONTHS.keys())})\.?\s"
            r"(?P<day>\d{1,2}),?\s"
            r"(?P<year>\d{4})\s"
            r"du\s"
            r"(?P<start_hour>\d{1,2})(?::(?P<start_minute>\d{2}))?\s?(?P<start_ampm>am|pm)\s"
            r"aux\s"
            r"(?P<end_hour>\d{1,2})(?::(?P<end_minute>\d{2}))?\s?(?P<end_ampm>am|pm)"
            r"(\s+(?P<timezone>CET|CEST|UTC[+-]?\d*))?",
            event_time,
            re.IGNORECASE,
        ):
            month_num = FRENCH_SHORT_MONTHS[match.group("month").lower()]
            day = int(match.group("day"))
            year = int(match.group("year"))

            # Parse start time with AM/PM
            start_hour = int(match.group("start_hour"))
            start_minute = int(match.group("start_minute") or 0)
            if match.group("start_ampm").lower() == "pm" and start_hour < 12:
                start_hour += 12
            elif match.group("start_ampm").lower() == "am" and start_hour == 12:
                start_hour = 0

            # Parse end time with AM/PM
            end_hour = int(match.group("end_hour"))
            end_minute = int(match.group("end_minute") or 0)
            if match.group("end_ampm").lower() == "pm" and end_hour < 12:
                end_hour += 12
            elif match.group("end_ampm").lower() == "am" and end_hour == 12:
                end_hour = 0

            event_start_datetime = datetime(year, month_num, day, start_hour, start_minute)
            event_end_datetime = datetime(year, month_num, day, end_hour, end_minute)

            return event_start_datetime, event_end_datetime

        else:
            raise FreskDateBadFormat(event_time)

    except Exception as e:
        if not isinstance(e, FreskError):
            traceback.print_exc()
        logging.error(f"get_dates: {event_time}")
        raise FreskDateBadFormat(event_time)


def get_dates_from_element(el):
    """Returns start and end datetime objects extracted from the element.

    The "datetime" attribute of the element is used if present to extract the date, otherwise falls back on get_dates to parse the day and hours from the element text. Returns None, None on failure.

    May throw FreskDateDifferentTimezone, FreskDateBadFormat and any exception thrown by get_dates.
    """
    event_day = el.get_attribute("datetime")
    event_time = el.text

    try:
        # Leverage the datetime attribute if present.
        # datetime: 2025-12-05
        # text: déc. 5 de 9am à 12pm UTC+1
        if event_day:
            day_match = re.match(r"(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})", event_day)

            def PATTERN_TIME(hour_name, minute_name, pm_name):
                return (
                    r"(?P<"
                    + hour_name
                    + r">\d{1,2})(?P<"
                    + minute_name
                    + r">:\d{2})?(?P<"
                    + pm_name
                    + r">(am|pm|vorm.|nachm.))"
                )

            def ParseTime(match_object, hour_name, minute_name, pm_name):
                hour = int(match_object.group(hour_name))
                PATTERN_PM = ["pm", "nachm."]
                if match_object.group(pm_name) in PATTERN_PM and hour < 12:
                    hour += 12

                minute = 0
                match_minute = hour_match.group(minute_name)
                if match_minute:
                    minute = int(match_minute[1:])

                return hour, minute

            # TODO: add proper support for timezone.
            # We use re.search to skip the text for the date at the beginning of the string.
            hour_match = re.search(
                r"(de|von)\s"
                + PATTERN_TIME("start_hour", "start_minute", "start_am_or_pm")
                + r"\s"
                + r"(à|bis)\s"
                + PATTERN_TIME("end_hour", "end_minute", "end_am_or_pm")
                + r"\s"
                + r"((UTC|MEZ)(?P<timezone>.*))",
                event_time,
            )
            if day_match and hour_match:
                timezone = hour_match.group("timezone")
                if timezone and timezone not in ("+1", "+2"):
                    raise FreskDateDifferentTimezone(event_time)
                dt = datetime(
                    int(day_match.group("year")),
                    int(day_match.group("month")),
                    int(day_match.group("day")),
                )
                start_hour, start_minute = ParseTime(
                    hour_match, "start_hour", "start_minute", "start_am_or_pm"
                )
                end_hour, end_minute = ParseTime(
                    hour_match, "end_hour", "end_minute", "end_am_or_pm"
                )
                return datetime(dt.year, dt.month, dt.day, start_hour, start_minute), datetime(
                    dt.year, dt.month, dt.day, end_hour, end_minute
                )

        return get_dates(event_time)

    except Exception as e:
        if not isinstance(e, FreskError):
            traceback.print_exc()
        logging.error(f"get_dates_from_element: {event_time}")
        raise FreskDateBadFormat(event_time)
