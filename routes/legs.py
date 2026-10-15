"""Flight legs CRUD.

A leg's origin and destination are copied from its flight schedule, so a leg
can never disagree with the schedule it belongs to. Actual times are optional
(unknown until the flight operates).
"""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from db import execute, query_all, query_one
from routes.helpers import datetime_input, parse_datetime, safe_delete

bp = Blueprint("legs", __name__, url_prefix="/legs")

LIST_COLUMNS = [("leg_id", "Leg ID"), ("flight_number", "Flight"), ("route", "Route"),
                ("scheduled_departure", "Scheduled departure"),
                ("actual_departure", "Actual departure"), ("actual_arrival", "Actual arrival"),
                ("reservations", "Reservations")]


def schedule_options():
    rows = query_all("SELECT flight_number, origin_airport_code, destination_airport_code "
                     "FROM flight_schedule ORDER BY flight_number")
    return [(r["flight_number"],
             f"{r['flight_number']} ({r['origin_airport_code']} to {r['destination_airport_code']})")
            for r in rows]


def build_fields(schedules):
    return [
        dict(name="flight_number", label="Flight schedule", type="select",
             options=schedules, required=True),
        dict(name="actual_departure", label="Actual departure (UTC, leave empty if unknown)",
             type="datetime-local"),
        dict(name="actual_arrival", label="Actual arrival (UTC, leave empty if unknown)",
             type="datetime-local"),
    ]


def clean(form):
    return {n: form.get(n, "").strip() for n in ("flight_number", "actual_departure", "actual_arrival")}


def validate(data, flight_numbers):
    errors, parsed = [], {}
    if data["flight_number"] not in flight_numbers:
        errors.append("Choose a valid flight schedule.")
    for name, label in (("actual_departure", "actual departure"), ("actual_arrival", "actual arrival")):
        try:
            parsed[name] = parse_datetime(data[name])
        except ValueError:
            parsed[name] = None
            errors.append(f"Enter a valid {label} date and time, or leave it empty.")
    dep, arr = parsed["actual_departure"], parsed["actual_arrival"]
    if arr and not dep:
        errors.append("An actual arrival needs an actual departure.")
    if dep and arr and arr <= dep:
        errors.append("Actual arrival must be after actual departure.")
    return errors, parsed


def render_form(heading, schedules, values):
    return render_template("crud_form.html", heading=heading, fields=build_fields(schedules),
                           values=values, cancel_url=url_for("legs.index"))


def get_or_404(item_id):
    row = query_one("SELECT * FROM flight_leg WHERE leg_id = %s", (item_id,))
    if row is None:
        abort(404)
    return row


def schedule_airports(flight_number):
    return query_one("SELECT origin_airport_code, destination_airport_code "
                     "FROM flight_schedule WHERE flight_number = %s", (flight_number,))


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    sql = ("SELECT l.leg_id, l.flight_number, "
           "CONCAT(l.origin_airport_code, ' to ', l.destination_airport_code) AS route, "
           "s.scheduled_departure, l.actual_departure, l.actual_arrival, "
           "(SELECT COUNT(*) FROM reservation_leg rl WHERE rl.leg_id = l.leg_id) AS reservations "
           "FROM flight_leg l JOIN flight_schedule s ON s.flight_number = l.flight_number")
    params = ()
    if q:
        like = f"%{q}%"
        sql += (" WHERE l.flight_number LIKE %s OR CAST(l.leg_id AS CHAR) = %s"
                " OR l.origin_airport_code LIKE %s OR l.destination_airport_code LIKE %s")
        params = (like, q, like, like)
    sql += " ORDER BY l.leg_id DESC LIMIT 200"
    return render_template("crud_list.html", title="Flight legs", singular="leg",
                           rows=query_all(sql, params), columns=LIST_COLUMNS, q=q,
                           placeholder="Search leg ID, flight number or airport code",
                           new_url=url_for("legs.create"), id_key="leg_id",
                           edit_endpoint="legs.edit", delete_endpoint="legs.delete")


@bp.route("/new", methods=["GET", "POST"])
def create():
    schedules = schedule_options()
    if request.method == "POST":
        data = clean(request.form)
        errors, parsed = validate(data, {s[0] for s in schedules})
        if not errors:
            airports = schedule_airports(data["flight_number"])
            execute("INSERT INTO flight_leg (flight_number, origin_airport_code, "
                    "destination_airport_code, actual_departure, actual_arrival) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (data["flight_number"], airports["origin_airport_code"],
                     airports["destination_airport_code"],
                     parsed["actual_departure"], parsed["actual_arrival"]))
            flash("Flight leg was created.", "success")
            return redirect(url_for("legs.index"))
        for message in errors:
            flash(message, "error")
        return render_form("New flight leg", schedules, data)
    return render_form("New flight leg", schedules, {})


@bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
def edit(item_id):
    row = get_or_404(item_id)
    schedules = schedule_options()
    heading = f"Edit flight leg {item_id}"
    if request.method == "POST":
        data = clean(request.form)
        errors, parsed = validate(data, {s[0] for s in schedules})
        if not errors:
            airports = schedule_airports(data["flight_number"])
            execute("UPDATE flight_leg SET flight_number = %s, origin_airport_code = %s, "
                    "destination_airport_code = %s, actual_departure = %s, actual_arrival = %s "
                    "WHERE leg_id = %s",
                    (data["flight_number"], airports["origin_airport_code"],
                     airports["destination_airport_code"],
                     parsed["actual_departure"], parsed["actual_arrival"], item_id))
            flash(f"Flight leg {item_id} was updated.", "success")
            return redirect(url_for("legs.index"))
        for message in errors:
            flash(message, "error")
        return render_form(heading, schedules, data)
    values = {"flight_number": row["flight_number"],
              "actual_departure": datetime_input(row["actual_departure"]),
              "actual_arrival": datetime_input(row["actual_arrival"])}
    return render_form(heading, schedules, values)


@bp.route("/<int:item_id>/delete", methods=["POST"])
def delete(item_id):
    get_or_404(item_id)
    safe_delete("flight_leg", "leg_id", item_id, f"Flight leg {item_id}", [
        ("reservation(s) (remove the links from those reservations first)",
         "SELECT COUNT(*) AS n FROM reservation_leg WHERE leg_id = %s"),
    ])
    return redirect(url_for("legs.index"))
