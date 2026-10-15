"""Passengers CRUD."""
import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from db import execute, query_all, query_one
from routes.helpers import check_text, safe_delete

bp = Blueprint("passengers", __name__, url_prefix="/passengers")

FIELDS = [
    dict(name="first_name", label="First name", type="text", maxlength=80, required=True),
    dict(name="second_name", label="Second name (optional)", type="text", maxlength=80),
    dict(name="last_name", label="Last name", type="text", maxlength=80, required=True),
    dict(name="phone", label="Phone", type="text", maxlength=30),
    dict(name="email", label="Email", type="email", maxlength=150),
    dict(name="address_line1", label="Address line 1", type="text", maxlength=150),
    dict(name="address_line2", label="Address line 2", type="text", maxlength=150),
    dict(name="city", label="City", type="text", maxlength=100),
    dict(name="state_province_county", label="State / province / county", type="text", maxlength=100),
    dict(name="country", label="Country", type="text", maxlength=100),
    dict(name="other_details", label="Other details", type="textarea", maxlength=2000),
]
COLUMNS = [f["name"] for f in FIELDS]
LIST_COLUMNS = [("passenger_id", "ID"), ("full_name", "Name"), ("email", "Email"),
                ("phone", "Phone"), ("city", "City"), ("country", "Country"),
                ("reservations", "Reservations")]
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PHONE_RE = re.compile(r"[0-9+\-(). xX]+")


def clean(form):
    data = {}
    for f in FIELDS:
        value = form.get(f["name"], "").strip()
        data[f["name"]] = value if f.get("required") else (value or None)
    return data


def validate(data):
    errors = []
    for f in FIELDS:
        check_text(errors, data[f["name"]], f["label"], f["maxlength"], f.get("required", False))
    if data["email"] and not EMAIL_RE.fullmatch(data["email"]):
        errors.append("Email address is not valid.")
    if data["phone"] and not PHONE_RE.fullmatch(data["phone"]):
        errors.append("Phone may only contain digits, spaces and + - ( ) . x")
    return errors


def render_form(heading, values):
    return render_template("crud_form.html", heading=heading, fields=FIELDS, values=values,
                           cancel_url=url_for("passengers.index"))


def get_or_404(item_id):
    row = query_one("SELECT * FROM passenger WHERE passenger_id = %s", (item_id,))
    if row is None:
        abort(404)
    return row


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    sql = ("SELECT p.passenger_id, CONCAT_WS(' ', p.first_name, p.second_name, p.last_name) AS full_name, "
           "p.email, p.phone, p.city, p.country, "
           "(SELECT COUNT(*) FROM reservation r WHERE r.passenger_id = p.passenger_id) AS reservations "
           "FROM passenger p")
    params = ()
    if q:
        like = f"%{q}%"
        sql += (" WHERE CONCAT_WS(' ', p.first_name, p.second_name, p.last_name) LIKE %s"
                " OR p.email LIKE %s OR p.city LIKE %s OR p.country LIKE %s")
        params = (like, like, like, like)
    sql += " ORDER BY p.last_name, p.first_name LIMIT 200"
    return render_template("crud_list.html", title="Passengers", singular="passenger",
                           rows=query_all(sql, params), columns=LIST_COLUMNS, q=q,
                           placeholder="Search name, email, city or country",
                           new_url=url_for("passengers.create"), id_key="passenger_id",
                           edit_endpoint="passengers.edit", delete_endpoint="passengers.delete")


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        data = clean(request.form)
        errors = validate(data)
        if not errors:
            execute(f"INSERT INTO passenger ({', '.join(COLUMNS)}) "
                    f"VALUES ({', '.join(['%s'] * len(COLUMNS))})",
                    tuple(data[c] for c in COLUMNS))
            flash("Passenger was created.", "success")
            return redirect(url_for("passengers.index"))
        for message in errors:
            flash(message, "error")
        return render_form("New passenger", data)
    return render_form("New passenger", {})


@bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
def edit(item_id):
    row = get_or_404(item_id)
    if request.method == "POST":
        data = clean(request.form)
        errors = validate(data)
        if not errors:
            execute("UPDATE passenger SET " + ", ".join(f"{c} = %s" for c in COLUMNS) +
                    " WHERE passenger_id = %s", tuple(data[c] for c in COLUMNS) + (item_id,))
            flash(f"Passenger {item_id} was updated.", "success")
            return redirect(url_for("passengers.index"))
        for message in errors:
            flash(message, "error")
        return render_form(f"Edit passenger {item_id}", data)
    return render_form(f"Edit passenger {item_id}", row)


@bp.route("/<int:item_id>/delete", methods=["POST"])
def delete(item_id):
    get_or_404(item_id)
    safe_delete("passenger", "passenger_id", item_id, f"Passenger {item_id}", [
        ("reservation(s)", "SELECT COUNT(*) AS n FROM reservation WHERE passenger_id = %s"),
    ])
    return redirect(url_for("passengers.index"))
