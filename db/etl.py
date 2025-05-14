import psycopg
import numpy as np
import pandas as pd
from time import sleep
import json

from utils.utils import get_config


def update_most_recent(conn, table):
    query = f"""
    WITH MissingRows AS (
        SELECT S."id", S."workshop_type", MAX(S."scrape_date") AS max_scrape_date
        FROM {table} S
        LEFT JOIN private.events_future F
        ON S."id" = F."id" AND S."workshop_type" = F."workshop_type"
        WHERE F."id" IS NULL
        GROUP BY S."id", S."workshop_type"
    )
    UPDATE {table} S
    SET "most_recent" = TRUE
    FROM MissingRows M
    WHERE S."id" = M."id" AND S."workshop_type" = M."workshop_type" AND S."scrape_date" = M.max_scrape_date AND S."start_date" < current_timestamp;
    """
    cursor = conn.cursor()
    print(query)
    try:
        cursor.execute(query)
        conn.commit()
    except (Exception, psycopg.DatabaseError) as error:
        print("Error: %s" % error)
        conn.rollback()
        cursor.close()
        return 1
    cursor.close()


def insert(conn, df, table, most_recent=False):
    df["most_recent"] = most_recent
    tuples = [tuple(x) for x in df.to_numpy()]
    cols = ",".join(list(df.columns))

    print(list(df.columns))

    # SQL query to execute
    cursor = conn.cursor()
    try:
        cursor.executemany(
            "INSERT INTO %s(%s) VALUES (%%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s)"
            % (table, cols),
            tuples,
            returning=True,
        )
        conn.commit()
    except (Exception, psycopg.DatabaseError) as error:
        print("Error: %s" % error)
        conn.rollback()
        cursor.close()
        return 1
    cursor.close()


def truncate(conn, table):
    query = "TRUNCATE TABLE %s" % table
    cursor = conn.cursor()
    try:
        cursor.execute(query)
        conn.commit()
    except (Exception, psycopg.DatabaseError) as error:
        print("Error: %s" % error)
        conn.rollback()
        cursor.close()
        return 1
    cursor.close()


def etl(conn, df):
    df = df.astype(str)

    # Insert all events to the historical table. Setting most_recent to False,
    # but maybe the call to `update_most_recent()` below will change this.
    insert(conn, df, "private.events_scraped", most_recent=False)

    # Delete all future events before inserting them again, so that they are
    # updated
    truncate(conn, "private.events_future")
    insert(conn, df, "private.events_future", most_recent=True)

    update_most_recent(conn, "private.events_scraped")
