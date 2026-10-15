"""Payments CRUD."""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from db import execute, query_all, query_one
from routes.helpers import safe_delete

bp = Blueprint("payments", __name__, url_prefix="/payments")

# Externally managed codes (demonstration values, same as the seed data).
PAYMENT_STATUS = ["PAID", "PENDING", "REFUNDED", "FAILED"]
MAX_AMOUNT = Decimal("9999999999.99")  # DECIMAL(12,2)

FIELDS = [
    dict(name="status_code", label="Status", type="select", options=PAYMENT_STATUS, required=True),
    dict(name="payment_date", label="Payment date and time (UTC)", type="datetime-local", required=True),
    dict(name="payment_amount", label="Amount", type="number", step="0.01", min="0.01", required=True),
]
LIST_COLUMNS = [("payment_id", "ID"), ("status_code", "Status"), ("payment_date", "Date (UTC)"),
                ("payment_amount", "Amount"), ("reservations", "Linked reservations")]


def clean(form):
    return {f["name"]: form.get(f["name"], "").strip() for f in FIELDS}


def validate(data):
    """Returns (errors, parsed) where parsed holds the converted date and amount."""
    errors, parsed = [], {}
    if data["status_code"] not in PAYMENT_STATUS:
        errors.append("Choose a valid payment status.")
    try:
        parsed["payment_date"] = datetime.fromisoformat(data["payment_date"])
    except ValueError:
        errors.append("Enter a valid payment date and time.")
    try:
        amount = Decimal(data["payment_amount"])
        if not amount.is_finite():
            raise InvalidOperation
        if amount <= 0:
            errors.append("Amount must be greater than zero.")
        elif amount.as_tuple().exponent < -2:
            errors.append("Amount can have at most 2 decimal places.")
        elif amount > MAX_AMOUNT:
            errors.append("Amount is too large.")
        else:
            parsed["payment_amount"] = amount
    except InvalidOperation:
        errors.append("Enter a valid amount, for example 250.00.")
    return errors, parsed


def render_form(heading, values):
    return render_template("crud_form.html", heading=heading, fields=FIELDS, values=values,
                           cancel_url=url_for("payments.index"))


def get_or_404(item_id):
    row = query_one("SELECT * FROM payment WHERE payment_id = %s", (item_id,))
    if row is None:
        abort(404)
    return row


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    sql = ("SELECT p.payment_id, p.status_code, p.payment_date, p.payment_amount, "
           "(SELECT COUNT(*) FROM reservation_payment rp WHERE rp.payment_id = p.payment_id) AS reservations "
           "FROM payment p")
    params = ()
    if q:
        sql += " WHERE p.status_code LIKE %s OR CAST(p.payment_id AS CHAR) = %s"
        params = (f"%{q}%", q)
    sql += " ORDER BY p.payment_date DESC LIMIT 200"
    return render_template("crud_list.html", title="Payments", singular="payment",
                           rows=query_all(sql, params), columns=LIST_COLUMNS, q=q,
                           placeholder="Search by status or payment ID",
                           new_url=url_for("payments.create"), id_key="payment_id",
                           edit_endpoint="payments.edit", delete_endpoint="payments.delete")


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        data = clean(request.form)
        errors, parsed = validate(data)
        if not errors:
            execute("INSERT INTO payment (status_code, payment_date, payment_amount) VALUES (%s, %s, %s)",
                    (data["status_code"], parsed["payment_date"], parsed["payment_amount"]))
            flash("Payment was created.", "success")
            return redirect(url_for("payments.index"))
        for message in errors:
            flash(message, "error")
        return render_form("New payment", data)
    return render_form("New payment", {})


@bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
def edit(item_id):
    row = get_or_404(item_id)
    if request.method == "POST":
        data = clean(request.form)
        errors, parsed = validate(data)
        if not errors:
            execute("UPDATE payment SET status_code = %s, payment_date = %s, payment_amount = %s "
                    "WHERE payment_id = %s",
                    (data["status_code"], parsed["payment_date"], parsed["payment_amount"], item_id))
            flash(f"Payment {item_id} was updated.", "success")
            return redirect(url_for("payments.index"))
        for message in errors:
            flash(message, "error")
        return render_form(f"Edit payment {item_id}", data)
    values = {"status_code": row["status_code"],
              "payment_date": row["payment_date"].strftime("%Y-%m-%dT%H:%M"),
              "payment_amount": str(row["payment_amount"])}
    return render_form(f"Edit payment {item_id}", values)


@bp.route("/<int:item_id>/delete", methods=["POST"])
def delete(item_id):
    get_or_404(item_id)
    safe_delete("payment", "payment_id", item_id, f"Payment {item_id}", [
        ("reservation(s) (remove the links from those reservations first)",
         "SELECT COUNT(*) AS n FROM reservation_payment WHERE payment_id = %s"),
    ])
    return redirect(url_for("payments.index"))
