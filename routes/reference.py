"""Read-only pages: calendar dates and reference codes."""
from flask import Blueprint, render_template, request

from db import query_all

bp = Blueprint("reference", __name__)

# Fixed queries (no user input). The codes are externally managed values, so
# this page lists the values that are actually in use in the data.
CODE_QUERIES = [
    ("Airline codes (flight schedules)",
     "SELECT airline_code AS code, COUNT(*) AS used FROM flight_schedule GROUP BY airline_code ORDER BY code"),
    ("Aircraft type codes (flight schedules)",
     "SELECT aircraft_type_code AS code, COUNT(*) AS used FROM flight_schedule GROUP BY aircraft_type_code ORDER BY code"),
    ("Reservation status codes",
     "SELECT status_code AS code, COUNT(*) AS used FROM reservation GROUP BY status_code ORDER BY code"),
    ("Ticket type codes",
     "SELECT ticket_type_code AS code, COUNT(*) AS used FROM reservation GROUP BY ticket_type_code ORDER BY code"),
    ("Travel class codes",
     "SELECT travel_class_code AS code, COUNT(*) AS used FROM reservation GROUP BY travel_class_code ORDER BY code"),
    ("Payment status codes",
     "SELECT status_code AS code, COUNT(*) AS used FROM payment GROUP BY status_code ORDER BY code"),
]


@bp.route("/calendar")
def calendar():
    q = request.args.get("q", "").strip()
    sql = ("SELECT calendar_date, day_of_month, IF(is_business_day, 'Yes', 'No') AS business_day "
           "FROM calendar_date")
    params = ()
    if q:
        sql += " WHERE CAST(calendar_date AS CHAR) LIKE %s"
        params = (q + "%",)
    sql += " ORDER BY calendar_date LIMIT 400"
    return render_template("crud_list.html", title="Calendar dates (read-only)", singular="date",
                           rows=query_all(sql, params), q=q,
                           columns=[("calendar_date", "Date"), ("day_of_month", "Day of month"),
                                    ("business_day", "Business day")],
                           placeholder="Type a year or month, e.g. 2026-10",
                           new_url=None, id_key="calendar_date",
                           edit_endpoint=None, delete_endpoint=None)


@bp.route("/reference")
def reference():
    sections = [(title, query_all(sql)) for title, sql in CODE_QUERIES]
    return render_template("reference.html", sections=sections)
