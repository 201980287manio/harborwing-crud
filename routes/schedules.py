"""Flight schedules CRUD."""
import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from mysql.connector import IntegrityError

from db import execute, query_all, query_one, run_transaction
from routes.helpers import check_text, datetime_input, parse_datetime, safe_delete

bp = Blueprint("schedules", __name__, url_prefix="/schedules")

FLIGHT_RE = re.compile(r"[A-Z0-9]{2,15}")
CODE_RE = re.compile(r"[A-Z0-9_-]+")
NAMES = ["flight_number", "airline_code", "aircraft_type_code", "origin_airport_code",
         "destination_airport_code", "scheduled_departure", "scheduled_arrival"]
LIST_COLUMNS = [("flight_number", "Flight"), ("airline_code", "Airline"),
                ("aircraft_type_code", "Aircraft"), ("route", "Route"),
                ("scheduled_departure", "Departs (UTC)"), ("scheduled_arrival", "Arrives (UTC)"),
                ("legs", "Legs"), ("costs", "Costs")]


def airport_options():
    rows = query_all("SELECT airport_code, airport_name FROM airport ORDER BY airport_code")
    return [(r["airport_code"], f"{r['airport_code']} - {r['airport_name']}") for r in rows]


def build_fields(editing, airports):
    return [
        dict(name="flight_number", label="Flight number", type="text", maxlength=15,
             required=True, readonly=editing),
        dict(name="airline_code", label="Airline code", type="text", maxlength=10, required=True),
        dict(name="aircraft_type_code", label="Usual aircraft type code", type="text",
             maxlength=20, required=True),
        dict(name="origin_airport_code", label="Origin airport", type="select",
             options=airports, required=True),
        dict(name="destination_airport_code", label="Destination airport", type="select",
             options=airports, required=True),
        dict(name="scheduled_departure", label="Scheduled departure (UTC)",
             type="datetime-local", required=True),
        dict(name="scheduled_arrival", label="Scheduled arrival (UTC)",
             type="datetime-local", required=True),
    ]


def clean(form):
    data = {n: form.get(n, "").strip() for n in NAMES}
    for n in NAMES[:5]:
        data[n] = data[n].upper()
    return data


def validate(data, airport_codes):
    errors, parsed = [], {}
    if not FLIGHT_RE.fullmatch(data["flight_number"]):
        errors.append("Flight number must be 2-15 letters or digits, with no spaces.")
    for name, label, limit in (("airline_code", "Airline code", 10),
                               ("aircraft_type_code", "Aircraft type code", 20)):
        check_text(errors, data[name], label, limit, required=True)
        if data[name] and not CODE_RE.fullmatch(data[name]):
            errors.append(f"{label} may only contain letters, digits, - and _.")
    if data["origin_airport_code"] not in airport_codes:
        errors.append("Choose a valid origin airport.")
    if data["destination_airport_code"] not in airport_codes:
        errors.append("Choose a valid destination airport.")
    if data["origin_airport_code"] == data["destination_airport_code"] and data["origin_airport_code"]:
        errors.append("Origin and destination airports must be different.")
    for name, label in (("scheduled_departure", "scheduled departure"),
                        ("scheduled_arrival", "scheduled arrival")):
        value = None
        try:
            value = parse_datetime(data[name])
        except ValueError:
            pass
        if value is None:
            errors.append(f"Enter a valid {label} date and time.")
        else:
            parsed[name] = value
    if len(parsed) == 2 and parsed["scheduled_arrival"] <= parsed["scheduled_departure"]:
        errors.append("Scheduled arrival must be after scheduled departure.")
    return errors, parsed


def render_form(heading, fields, values):
    return render_template("crud_form.html", heading=heading, fields=fields, values=values,
                           cancel_url=url_for("schedules.index"))


def get_or_404(item_id):
    row = query_one("SELECT * FROM flight_schedule WHERE flight_number = %s", (item_id,))
    if row is None:
        abort(404)
    return row


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    sql = ("SELECT s.flight_number, s.airline_code, s.aircraft_type_code, "
           "CONCAT(s.origin_airport_code, ' to ', s.destination_airport_code) AS route, "
           "s.scheduled_departure, s.scheduled_arrival, "
           "(SELECT COUNT(*) FROM flight_leg l WHERE l.flight_number = s.flight_number) AS legs, "
           "(SELECT COUNT(*) FROM flight_cost c WHERE c.flight_number = s.flight_number) AS costs "
           "FROM flight_schedule s")
    params = ()
    if q:
        like = f"%{q}%"
        sql += (" WHERE s.flight_number LIKE %s OR s.origin_airport_code LIKE %s"
                " OR s.destination_airport_code LIKE %s")
        params = (like, like, like)
    sql += " ORDER BY s.scheduled_departure LIMIT 200"
    return render_template("crud_list.html", title="Flight schedules", singular="schedule",
                           rows=query_all(sql, params), columns=LIST_COLUMNS, q=q,
                           placeholder="Search flight number or airport code",
                           new_url=url_for("schedules.create"), id_key="flight_number",
                           edit_endpoint="schedules.edit", delete_endpoint="schedules.delete")


@bp.route("/new", methods=["GET", "POST"])
def create():
    airports = airport_options()
    fields = build_fields(False, airports)
    if request.method == "POST":
        data = clean(request.form)
        errors, parsed = validate(data, {a[0] for a in airports})
        if not errors:
            try:
                execute("INSERT INTO flight_schedule (flight_number, airline_code, aircraft_type_code, "
                        "origin_airport_code, destination_airport_code, scheduled_departure, "
                        "scheduled_arrival) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (data["flight_number"], data["airline_code"], data["aircraft_type_code"],
                         data["origin_airport_code"], data["destination_airport_code"],
                         parsed["scheduled_departure"], parsed["scheduled_arrival"]))
                flash(f"Flight schedule {data['flight_number']} was created.", "success")
                return redirect(url_for("schedules.index"))
            except IntegrityError as exc:
                if exc.errno == 1062:
                    errors.append(f"Flight number {data['flight_number']} already exists.")
                else:
                    raise
        for message in errors:
            flash(message, "error")
        return render_form("New flight schedule", fields, data)
    return render_form("New flight schedule", fields, {})


@bp.route("/<item_id>/edit", methods=["GET", "POST"])
def edit(item_id):
    row = get_or_404(item_id)
    airports = airport_options()
    fields = build_fields(True, airports)
    heading = f"Edit flight schedule {item_id}"
    if request.method == "POST":
        data = clean(request.form)
        data["flight_number"] = item_id  # the flight number is never changed
        errors, parsed = validate(data, {a[0] for a in airports})
        if not errors:
            # Two tables change together, so use ONE transaction: legs keep a copy
            # of the schedule's airports and must stay consistent with it.
            run_transaction([
                ("UPDATE flight_schedule SET airline_code = %s, aircraft_type_code = %s, "
                 "origin_airport_code = %s, destination_airport_code = %s, "
                 "scheduled_departure = %s, scheduled_arrival = %s WHERE flight_number = %s",
                 (data["airline_code"], data["aircraft_type_code"], data["origin_airport_code"],
                  data["destination_airport_code"], parsed["scheduled_departure"],
                  parsed["scheduled_arrival"], item_id)),
                ("UPDATE flight_leg SET origin_airport_code = %s, destination_airport_code = %s "
                 "WHERE flight_number = %s",
                 (data["origin_airport_code"], data["destination_airport_code"], item_id)),
            ])
            flash(f"Flight schedule {item_id} was updated (its legs were kept in sync).", "success")
            return redirect(url_for("schedules.index"))
        for message in errors:
            flash(message, "error")
        return render_form(heading, fields, data)
    values = dict(row)
    values["scheduled_departure"] = datetime_input(row["scheduled_departure"])
    values["scheduled_arrival"] = datetime_input(row["scheduled_arrival"])
    return render_form(heading, fields, values)


@bp.route("/<item_id>/delete", methods=["POST"])
def delete(item_id):
    get_or_404(item_id)
    safe_delete("flight_schedule", "flight_number", item_id, f"Flight schedule {item_id}", [
        ("flight leg(s)", "SELECT COUNT(*) AS n FROM flight_leg WHERE flight_number = %s"),
        ("cost record(s)", "SELECT COUNT(*) AS n FROM flight_cost WHERE flight_number = %s"),
    ])
    return redirect(url_for("schedules.index"))
