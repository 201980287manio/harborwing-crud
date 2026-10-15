"""Flight costs CRUD.

A cost record is identified by THREE values (flight number, aircraft type,
valid-from date). In the URL they are joined with '~', e.g.
/costs/HW101~A320~2026-07-05/edit
Policy for overlapping periods: the application rejects a period that overlaps
another period of the same flight and aircraft type.
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from mysql.connector import IntegrityError

from db import execute, query_all, query_one
from routes.helpers import check_text

bp = Blueprint("costs", __name__, url_prefix="/costs")

CODE_RE = re.compile(r"[A-Z0-9_-]+")
MAX_AMOUNT = Decimal("9999999999.99")  # DECIMAL(12,2)
LIST_COLUMNS = [("flight_number", "Flight"), ("aircraft_type_code", "Aircraft"),
                ("valid_from", "Valid from"), ("valid_to", "Valid to"), ("cost_amount", "Cost")]


def flight_options():
    rows = query_all("SELECT flight_number FROM flight_schedule ORDER BY flight_number")
    return [r["flight_number"] for r in rows]


def build_fields(editing, flights):
    if editing:
        key_fields = [
            dict(name="flight_number", label="Flight number", type="text", readonly=True),
            dict(name="aircraft_type_code", label="Aircraft type code", type="text", readonly=True),
            dict(name="valid_from", label="Valid from", type="date", readonly=True),
        ]
    else:
        key_fields = [
            dict(name="flight_number", label="Flight schedule", type="select",
                 options=flights, required=True),
            dict(name="aircraft_type_code", label="Aircraft type code", type="text",
                 maxlength=20, required=True),
            dict(name="valid_from", label="Valid from", type="date", required=True),
        ]
    return key_fields + [
        dict(name="valid_to", label="Valid to", type="date", required=True),
        dict(name="cost_amount", label="Cost amount", type="number", step="0.01",
             min="0", required=True),
    ]


def clean(form):
    data = {n: form.get(n, "").strip() for n in
            ("flight_number", "aircraft_type_code", "valid_from", "valid_to", "cost_amount")}
    data["flight_number"] = data["flight_number"].upper()
    data["aircraft_type_code"] = data["aircraft_type_code"].upper()
    return data


def parse_key(item_id):
    parts = item_id.split("~")
    if len(parts) != 3:
        abort(404)
    try:
        return parts[0], parts[1], date.fromisoformat(parts[2])
    except ValueError:
        abort(404)


def get_or_404(item_id):
    flight, aircraft, valid_from = parse_key(item_id)
    row = query_one("SELECT * FROM flight_cost WHERE flight_number = %s "
                    "AND aircraft_type_code = %s AND valid_from = %s", (flight, aircraft, valid_from))
    if row is None:
        abort(404)
    return row


def validate(data, flights, creating):
    errors, parsed = [], {}
    if creating:
        if data["flight_number"] not in flights:
            errors.append("Choose a valid flight schedule.")
        check_text(errors, data["aircraft_type_code"], "Aircraft type code", 20, required=True)
        if data["aircraft_type_code"] and not CODE_RE.fullmatch(data["aircraft_type_code"]):
            errors.append("Aircraft type code may only contain letters, digits, - and _.")
    for name, label in (("valid_from", "valid-from"), ("valid_to", "valid-to")):
        try:
            parsed[name] = date.fromisoformat(data[name])
        except ValueError:
            errors.append(f"Enter a valid {label} date.")
    try:
        amount = Decimal(data["cost_amount"])
        if not amount.is_finite():
            raise InvalidOperation
        if amount < 0:
            errors.append("Cost must not be negative.")
        elif amount.as_tuple().exponent < -2:
            errors.append("Cost can have at most 2 decimal places.")
        elif amount > MAX_AMOUNT:
            errors.append("Cost is too large.")
        else:
            parsed["cost_amount"] = amount
    except InvalidOperation:
        errors.append("Enter a valid cost, for example 4500.00.")
    if "valid_from" in parsed and "valid_to" in parsed:
        start, end = parsed["valid_from"], parsed["valid_to"]
        if end < start:
            errors.append("The valid-to date must not be before the valid-from date.")
        else:
            wanted = sorted({start, end})
            found = query_one("SELECT COUNT(*) AS n FROM calendar_date WHERE calendar_date IN ("
                              + ", ".join(["%s"] * len(wanted)) + ")", tuple(wanted))["n"]
            if found != len(wanted):
                errors.append("Both dates must exist in the calendar table "
                              "(the seed data covers 2026-01-01 to 2027-12-31).")
            elif not errors:
                sql = ("SELECT valid_from, valid_to FROM flight_cost WHERE flight_number = %s "
                       "AND aircraft_type_code = %s AND valid_from <= %s AND valid_to >= %s")
                params = [data["flight_number"], data["aircraft_type_code"], end, start]
                if not creating:
                    sql += " AND valid_from <> %s"   # ignore the record being edited
                    params.append(start)
                overlap = query_one(sql + " LIMIT 1", tuple(params))
                if overlap:
                    errors.append(f"This period overlaps an existing cost period for this flight and "
                                  f"aircraft ({overlap['valid_from']} to {overlap['valid_to']}). "
                                  f"Overlapping periods are not allowed.")
    return errors, parsed


def render_form(heading, fields, values):
    return render_template("crud_form.html", heading=heading, fields=fields, values=values,
                           cancel_url=url_for("costs.index"))


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    sql = ("SELECT CONCAT_WS('~', c.flight_number, c.aircraft_type_code, c.valid_from) AS cost_key, "
           "c.flight_number, c.aircraft_type_code, c.valid_from, c.valid_to, c.cost_amount "
           "FROM flight_cost c")
    params = ()
    if q:
        like = f"%{q}%"
        sql += " WHERE c.flight_number LIKE %s OR c.aircraft_type_code LIKE %s"
        params = (like, like)
    sql += " ORDER BY c.flight_number, c.aircraft_type_code, c.valid_from LIMIT 300"
    return render_template("crud_list.html", title="Flight costs", singular="cost record",
                           rows=query_all(sql, params), columns=LIST_COLUMNS, q=q,
                           placeholder="Search flight number or aircraft type",
                           new_url=url_for("costs.create"), id_key="cost_key",
                           edit_endpoint="costs.edit", delete_endpoint="costs.delete")


@bp.route("/new", methods=["GET", "POST"])
def create():
    flights = flight_options()
    fields = build_fields(False, flights)
    if request.method == "POST":
        data = clean(request.form)
        errors, parsed = validate(data, flights, creating=True)
        if not errors:
            try:
                execute("INSERT INTO flight_cost (flight_number, aircraft_type_code, valid_from, "
                        "valid_to, cost_amount) VALUES (%s, %s, %s, %s, %s)",
                        (data["flight_number"], data["aircraft_type_code"], parsed["valid_from"],
                         parsed["valid_to"], parsed["cost_amount"]))
                flash("Cost record was created.", "success")
                return redirect(url_for("costs.index"))
            except IntegrityError as exc:
                if exc.errno == 1062:
                    errors.append("A cost record with this flight, aircraft type and valid-from date already exists.")
                else:
                    raise
        for message in errors:
            flash(message, "error")
        return render_form("New flight cost", fields, data)
    return render_form("New flight cost", fields, {})


@bp.route("/<item_id>/edit", methods=["GET", "POST"])
def edit(item_id):
    row = get_or_404(item_id)
    fields = build_fields(True, [])
    heading = f"Edit cost {item_id}"
    if request.method == "POST":
        data = clean(request.form)
        # The three key values come from the URL, never from the form.
        data.update(flight_number=row["flight_number"], aircraft_type_code=row["aircraft_type_code"],
                    valid_from=str(row["valid_from"]))
        errors, parsed = validate(data, [], creating=False)
        if not errors:
            execute("UPDATE flight_cost SET valid_to = %s, cost_amount = %s WHERE flight_number = %s "
                    "AND aircraft_type_code = %s AND valid_from = %s",
                    (parsed["valid_to"], parsed["cost_amount"], row["flight_number"],
                     row["aircraft_type_code"], row["valid_from"]))
            flash("Cost record was updated.", "success")
            return redirect(url_for("costs.index"))
        for message in errors:
            flash(message, "error")
        return render_form(heading, fields, data)
    values = {k: str(v) for k, v in row.items()}
    return render_form(heading, fields, values)


@bp.route("/<item_id>/delete", methods=["POST"])
def delete(item_id):
    row = get_or_404(item_id)
    execute("DELETE FROM flight_cost WHERE flight_number = %s AND aircraft_type_code = %s "
            "AND valid_from = %s", (row["flight_number"], row["aircraft_type_code"], row["valid_from"]))
    flash("Cost record was deleted.", "success")
    return redirect(url_for("costs.index"))
