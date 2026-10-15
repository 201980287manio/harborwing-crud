"""Airports CRUD - the template pattern for the other modules."""
import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from mysql.connector import IntegrityError

from db import execute, query_all, query_one

bp = Blueprint("airports", __name__, url_prefix="/airports")


def clean(form):
    """Trim input; empty optional fields become NULL."""
    return {
        "airport_code": form.get("airport_code", "").strip().upper(),
        "airport_name": form.get("airport_name", "").strip(),
        "city": form.get("city", "").strip(),
        "state_province_county": form.get("state_province_county", "").strip() or None,
        "country": form.get("country", "").strip(),
        "other_details": form.get("other_details", "").strip() or None,
    }


def validate(data, creating):
    errors = []
    if creating and not re.fullmatch(r"[A-Z]{3}", data["airport_code"]):
        errors.append("Airport code must be exactly 3 letters (A-Z).")
    for field, label, limit in (("airport_name", "Airport name", 150),
                                ("city", "City", 100),
                                ("country", "Country", 100)):
        if not data[field]:
            errors.append(f"{label} is required.")
        elif len(data[field]) > limit:
            errors.append(f"{label} must be at most {limit} characters.")
    if data["state_province_county"] and len(data["state_province_county"]) > 100:
        errors.append("State/province/county must be at most 100 characters.")
    return errors


def get_or_404(code):
    airport = query_one("SELECT * FROM airport WHERE airport_code = %s", (code,))
    if airport is None:
        abort(404)
    return airport


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    if q:
        like = f"%{q}%"
        rows = query_all(
            "SELECT * FROM airport WHERE airport_code LIKE %s OR airport_name LIKE %s "
            "OR city LIKE %s OR country LIKE %s ORDER BY airport_code LIMIT 200",
            (like, like, like, like))
    else:
        rows = query_all("SELECT * FROM airport ORDER BY airport_code LIMIT 200")
    return render_template("airports/list.html", airports=rows, q=q)


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        data = clean(request.form)
        errors = validate(data, creating=True)
        if not errors:
            try:
                execute(
                    "INSERT INTO airport (airport_code, airport_name, city, "
                    "state_province_county, country, other_details) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (data["airport_code"], data["airport_name"], data["city"],
                     data["state_province_county"], data["country"], data["other_details"]))
                flash(f"Airport {data['airport_code']} was created.", "success")
                return redirect(url_for("airports.index"))
            except IntegrityError as exc:
                if exc.errno == 1062:  # duplicate primary key
                    errors.append(f"An airport with code {data['airport_code']} already exists.")
                else:
                    raise
        for message in errors:
            flash(message, "error")
        return render_template("airports/form.html", airport=data, creating=True)
    return render_template("airports/form.html", airport={}, creating=True)


@bp.route("/<code>/edit", methods=["GET", "POST"])
def edit(code):
    airport = get_or_404(code)
    if request.method == "POST":
        data = clean(request.form)
        data["airport_code"] = airport["airport_code"]  # the code is never changed
        errors = validate(data, creating=False)
        if not errors:
            execute(
                "UPDATE airport SET airport_name = %s, city = %s, "
                "state_province_county = %s, country = %s, other_details = %s "
                "WHERE airport_code = %s",
                (data["airport_name"], data["city"], data["state_province_county"],
                 data["country"], data["other_details"], code))
            flash(f"Airport {code} was updated.", "success")
            return redirect(url_for("airports.index"))
        for message in errors:
            flash(message, "error")
        return render_template("airports/form.html", airport=data, creating=False)
    return render_template("airports/form.html", airport=airport, creating=False)


@bp.route("/<code>/delete", methods=["POST"])
def delete(code):
    get_or_404(code)
    # Friendly pre-check: explain WHY a referenced airport cannot be deleted.
    usage = query_one(
        "SELECT (SELECT COUNT(*) FROM flight_schedule "
        "        WHERE origin_airport_code = %s OR destination_airport_code = %s) AS schedules, "
        "       (SELECT COUNT(*) FROM flight_leg "
        "        WHERE origin_airport_code = %s OR destination_airport_code = %s) AS legs",
        (code, code, code, code))
    if usage["schedules"] or usage["legs"]:
        flash(f"Airport {code} cannot be deleted: it is used by {usage['schedules']} "
              f"flight schedule(s) and {usage['legs']} flight leg(s).", "error")
        return redirect(url_for("airports.index"))
    try:
        execute("DELETE FROM airport WHERE airport_code = %s", (code,))
        flash(f"Airport {code} was deleted.", "success")
    except IntegrityError as exc:
        if exc.errno == 1451:  # foreign key still references it (safety net)
            flash(f"Airport {code} is still referenced by other records and was not deleted.", "error")
        else:
            raise
    return redirect(url_for("airports.index"))
