create table "private"."events_future" (
    "id" character varying,
    "workshop_type" bigint,
    "title" text,
    "description" text,
    "online" boolean,
    "training" boolean,
    "sold_out" boolean,
    "kids" boolean,
    "start_date" timestamptz,
    "end_date" timestamptz,
    "zip_code" character varying,
    "latitude" character varying,
    "longitude" character varying,
    "source_link" character varying,
    "tickets_link" character varying,
    "country_code" character varying,
    "department" character varying,
    "city" character varying,
    "address" character varying,
    "location_name" character varying,
    "full_location" character varying,
    "scrape_date" timestamp with time zone,
    "most_recent" boolean default false
);

create table "private"."events_scraped" (
    like "private"."events_future"
);

create view "public"."events" as ( 
    select * from "private"."events_future"
    union all
    select * from "private"."events_scraped" where most_recent = true
);

alter table "private"."events_future" enable row level security;
alter table "private"."events_scraped" enable row level security;
