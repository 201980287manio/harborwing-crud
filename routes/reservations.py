"""Reservations: CRUD, the full detail view, and payment/leg link management.

Key ideas for the explainer video:
  * Payments and legs are loaded with SEPARATE queries and totals are summed over
    payments only, so joining both never multiplies (inflates) payment amounts.
  * Removing a link deletes ONLY the row in the linking table.
  * Duplicate links are blocked by the composite primary key; the 1062 error is
    turned into a friendly message.
  * "Create and link a payment" is ONE transaction (both inserts or neither).
"""
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from mysql.connector import IntegrityError

from db import execute, query_all, query_one, transaction
from routes import payments as payments_module

bp = Blueprint("reservations", __name__, url_prefix="/reservations")

# Externally managed codes (demonstration values, same as the seed data).
RESERVATION_STATUS = ["CONFIRMED", "PENDING", "CANCELLED", "CHECKED_IN"]
TICKET_TYPES = ["ONE_WAY", "ROUND_TRIP", "MULTI_CITY"]
TRAVEL_CLASSES = ["ECONOMY", "PREMIUM", "BUSINESS"]
NAMES = ["passenger_id", "agent_id", "status_code", "ticket_type_code",
         "travel_class_code", "party_size"]
LIST_COLUMNS = [("reservation_id", "ID"), ("passenger", "Passenger"), ("agent", "Agent"),
                ("status_code", "Status"), ("ticket_type_code", "Ticket"),
                ("travel_class_code", "Class"), ("party_size", "Party"),
                ("created_at", "Created (UTC)"), ("payments", "Payments"), ("legs", "Legs")]


# ------------------------------------------------------------ form helpers
def passenger_options():
    rows = query_all("SELECT passenger_id, first_name, last_name FROM passenger "
                     "ORDER BY last_name, first_name")
    return [(str(r["passenger_id"]), f"{r['passenger_id']} - {r['last_name']}, {r['first_name']}")
            for r in rows]


def agent_options():
    rows = query_all("SELECT agent_id, agent_name FROM booking_agent ORDER BY agent_name")
    return [("", "(direct booking - no agent)")] + \
           [(str(r["agent_id"]), f"{r['agent_id']} - {r['agent_name']}") for r in rows]


def build_fields(passengers, agents):
    return [
        dict(name="passenger_id", label="Main passenger", type="select", options=passengers, required=True),
        dict(name="agent_id", label="Booking agent (optional)", type="select", options=agents),
        dict(name="status_code", label="Status", type="select", options=RESERVATION_STATUS, required=True),
        dict(name="ticket_type_code", label="Ticket type", type="select", options=TICKET_TYPES, required=True),
        dict(name="travel_class_code", label="Travel class", type="select", options=TRAVEL_CLASSES, required=True),
        dict(name="party_size", label="Number in party", type="number", step="1", min="1", required=True),
    ]


def clean(form):
    return {n: form.get(n, "").strip() for n in NAMES}


def validate(data, passenger_ids, agent_ids):
    errors, parsed = [], {}
    if data["passenger_id"] not in passenger_ids:
        errors.append("Choose a valid main passenger.")
    else:
        parsed["passenger_id"] = int(data["passenger_id"])
    if data["agent_id"] == "":
        parsed["agent_id"] = None
    elif data["agent_id"] in agent_ids:
        parsed["agent_id"] = int(data["agent_id"])
    else:
        errors.append("Choose a valid booking agent, or leave it as a direct booking.")
    for name, label, allowed in (("status_code", "status", RESERVATION_STATUS),
                                 ("ticket_type_code", "ticket type", TICKET_TYPES),
                                 ("travel_class_code", "travel class", TRAVEL_CLASSES)):
        if data[name] not in allowed:
            errors.append(f"Choose a valid {label}.")
    try:
        party = int(data["party_size"])
    except ValueError:
        party = None
    if party is None or not 1 <= party <= 500:
        errors.append("Number in party must be a whole number from 1 to 500.")
    else:
        parsed["party_size"] = party
    return errors, parsed


def render_form(heading, values):
    passengers, agents = passenger_options(), agent_options()
    return render_template("crud_form.html", heading=heading, fields=build_fields(passengers, agents),
                           values=values, cancel_url=url_for("reservations.index"))


def valid_ids():
    return ({o[0] for o in passenger_options()}, {o[0] for o in agent_options() if o[0]})


def get_or_404(item_id):
    row = query_one("SELECT * FROM reservation WHERE reservation_id = %s", (item_id,))
    if row is None:
        abort(404)
    return row


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)  # stored as UTC


# --------------------------------------------------------------- CRUD
@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    sql = ("SELECT r.reservation_id, CONCAT_WS(' ', p.first_name, p.last_name) AS passenger, "
           "COALESCE(a.agent_name, '(direct)') AS agent, r.status_code, r.ticket_type_code, "
           "r.travel_class_code, r.party_size, r.created_at, "
           "(SELECT COUNT(*) FROM reservation_payment rp WHERE rp.reservation_id = r.reservation_id) AS payments, "
           "(SELECT COUNT(*) FROM reservation_leg rl WHERE rl.reservation_id = r.reservation_id) AS legs "
           "FROM reservation r JOIN passenger p ON p.passenger_id = r.passenger_id "
           "LEFT JOIN booking_agent a ON a.agent_id = r.agent_id")
    params = ()
    if q:
        like = f"%{q}%"
        sql += (" WHERE CAST(r.reservation_id AS CHAR) = %s"
                " OR CONCAT_WS(' ', p.first_name, p.last_name) LIKE %s"
                " OR a.agent_name LIKE %s OR r.status_code LIKE %s")
        params = (q, like, like, like)
    sql += " ORDER BY r.reservation_id DESC LIMIT 200"
    return render_template("crud_list.html", title="Reservations", singular="reservation",
                           rows=query_all(sql, params), columns=LIST_COLUMNS, q=q,
                           placeholder="Search reservation ID, passenger, agent or status",
                           new_url=url_for("reservations.create"), id_key="reservation_id",
                           view_endpoint="reservations.detail",
                           edit_endpoint="reservations.edit", delete_endpoint="reservations.delete")


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        data = clean(request.form)
        passenger_ids, agent_ids = valid_ids()
        errors, parsed = validate(data, passenger_ids, agent_ids)
        if not errors:
            with transaction() as cur:
                cur.execute("INSERT INTO reservation (passenger_id, agent_id, status_code, "
                            "ticket_type_code, travel_class_code, created_at, party_size) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            (parsed["passenger_id"], parsed["agent_id"], data["status_code"],
                             data["ticket_type_code"], data["travel_class_code"],
                             utc_now(), parsed["party_size"]))
                new_id = cur.lastrowid
            flash(f"Reservation {new_id} was created. Add its flight legs and payments below.", "success")
            return redirect(url_for("reservations.detail", item_id=new_id))
        for message in errors:
            flash(message, "error")
        return render_form("New reservation", data)
    return render_form("New reservation", {})


@bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
def edit(item_id):
    row = get_or_404(item_id)
    heading = f"Edit reservation {item_id}"
    if request.method == "POST":
        data = clean(request.form)
        passenger_ids, agent_ids = valid_ids()
        errors, parsed = validate(data, passenger_ids, agent_ids)
        if not errors:
            execute("UPDATE reservation SET passenger_id = %s, agent_id = %s, status_code = %s, "
                    "ticket_type_code = %s, travel_class_code = %s, party_size = %s "
                    "WHERE reservation_id = %s",
                    (parsed["passenger_id"], parsed["agent_id"], data["status_code"],
                     data["ticket_type_code"], data["travel_class_code"],
                     parsed["party_size"], item_id))
            flash(f"Reservation {item_id} was updated.", "success")
            return redirect(url_for("reservations.detail", item_id=item_id))
        for message in errors:
            flash(message, "error")
        return render_form(heading, data)
    values = {n: ("" if row[n] is None else str(row[n])) for n in NAMES}
    return render_form(heading, values)


@bp.route("/<int:item_id>/delete", methods=["POST"])
def delete(item_id):
    get_or_404(item_id)
    # Policy: deleting a reservation removes ONLY its link rows (ON DELETE CASCADE
    # on the linking tables). The payments and legs themselves are kept.
    execute("DELETE FROM reservation WHERE reservation_id = %s", (item_id,))
    flash(f"Reservation {item_id} was deleted. Its payment and leg links were removed; "
          f"the payments and legs themselves were kept.", "success")
    return redirect(url_for("reservations.index"))


# ------------------------------------------------- complete reservation view
@bp.route("/<int:item_id>")
def detail(item_id):
    reservation = query_one(
        "SELECT r.*, p.first_name, p.second_name, p.last_name, p.email, p.phone, a.agent_name "
        "FROM reservation r JOIN passenger p ON p.passenger_id = r.passenger_id "
        "LEFT JOIN booking_agent a ON a.agent_id = r.agent_id WHERE r.reservation_id = %s", (item_id,))
    if reservation is None:
        abort(404)
    # Separate queries on purpose: joining payments AND legs in one query would
    # repeat every payment once per leg and inflate totals.
    payments = query_all(
        "SELECT pay.payment_id, pay.status_code, pay.payment_date, pay.payment_amount, "
        "(SELECT COUNT(*) FROM reservation_payment x WHERE x.payment_id = pay.payment_id) AS shared_count "
        "FROM reservation_payment rp JOIN payment pay ON pay.payment_id = rp.payment_id "
        "WHERE rp.reservation_id = %s ORDER BY pay.payment_date", (item_id,))
    totals = query_one(
        "SELECT COALESCE(SUM(pay.payment_amount), 0) AS total_all, "
        "COALESCE(SUM(CASE WHEN pay.status_code = 'PAID' THEN pay.payment_amount ELSE 0 END), 0) AS total_paid "
        "FROM reservation_payment rp JOIN payment pay ON pay.payment_id = rp.payment_id "
        "WHERE rp.reservation_id = %s", (item_id,))
    legs = query_all(
        "SELECT l.leg_id, l.flight_number, l.origin_airport_code, l.destination_airport_code, "
        "s.scheduled_departure, s.scheduled_arrival, l.actual_departure, l.actual_arrival, "
        "(SELECT COUNT(*) FROM reservation_leg x WHERE x.leg_id = l.leg_id) AS shared_count "
        "FROM reservation_leg rl JOIN flight_leg l ON l.leg_id = rl.leg_id "
        "JOIN flight_schedule s ON s.flight_number = l.flight_number "
        "WHERE rl.reservation_id = %s ORDER BY COALESCE(l.actual_departure, s.scheduled_departure)",
        (item_id,))
    available_payments = query_all(
        "SELECT payment_id, status_code, payment_amount, payment_date FROM payment "
        "WHERE payment_id NOT IN (SELECT payment_id FROM reservation_payment WHERE reservation_id = %s) "
        "ORDER BY payment_id DESC LIMIT 300", (item_id,))
    available_legs = query_all(
        "SELECT l.leg_id, l.flight_number, l.origin_airport_code, l.destination_airport_code, "
        "s.scheduled_departure FROM flight_leg l JOIN flight_schedule s ON s.flight_number = l.flight_number "
        "WHERE l.leg_id NOT IN (SELECT leg_id FROM reservation_leg WHERE reservation_id = %s) "
        "ORDER BY l.leg_id DESC LIMIT 300", (item_id,))
    return render_template("reservations/detail.html", r=reservation, payments=payments,
                           totals=totals, legs=legs, available_payments=available_payments,
                           available_legs=available_legs,
                           payment_statuses=payments_module.PAYMENT_STATUS)


# ------------------------------------------------------- payment links
@bp.route("/<int:item_id>/payments/add", methods=["POST"])
def add_payment(item_id):
    get_or_404(item_id)
    raw = request.form.get("payment_id", "")
    payment = query_one("SELECT payment_id FROM payment WHERE payment_id = %s", (raw,)) if raw.isdigit() else None
    if payment is None:
        flash("Choose a payment that exists.", "error")
    else:
        try:
            execute("INSERT INTO reservation_payment (reservation_id, payment_id) VALUES (%s, %s)",
                    (item_id, payment["payment_id"]))
            flash(f"Payment {payment['payment_id']} was linked to reservation {item_id}.", "success")
        except IntegrityError as exc:
            if exc.errno == 1062:  # composite primary key blocks duplicate pairs
                flash(f"Payment {payment['payment_id']} is already linked to this reservation.", "error")
            else:
                raise
    return redirect(url_for("reservations.detail", item_id=item_id))


@bp.route("/<int:item_id>/payments/<int:payment_id>/remove", methods=["POST"])
def remove_payment(item_id, payment_id):
    get_or_404(item_id)
    removed = execute("DELETE FROM reservation_payment WHERE reservation_id = %s AND payment_id = %s",
                      (item_id, payment_id))
    if removed:
        flash(f"The link to payment {payment_id} was removed. The payment itself still exists.", "success")
    else:
        flash("That payment is not linked to this reservation.", "error")
    return redirect(url_for("reservations.detail", item_id=item_id))


@bp.route("/<int:item_id>/payments/new", methods=["POST"])
def new_payment(item_id):
    """Create a payment AND link it, as one transaction."""
    get_or_404(item_id)
    data = payments_module.clean(request.form)
    errors, parsed = payments_module.validate(data)
    if errors:
        for message in errors:
            flash(message, "error")
        return redirect(url_for("reservations.detail", item_id=item_id))
    with transaction() as cur:
        cur.execute("INSERT INTO payment (status_code, payment_date, payment_amount) VALUES (%s, %s, %s)",
                    (data["status_code"], parsed["payment_date"], parsed["payment_amount"]))
        new_id = cur.lastrowid
        cur.execute("INSERT INTO reservation_payment (reservation_id, payment_id) VALUES (%s, %s)",
                    (item_id, new_id))
    flash(f"Payment {new_id} was created and linked to reservation {item_id}.", "success")
    return redirect(url_for("reservations.detail", item_id=item_id))


# ------------------------------------------------------------ leg links
@bp.route("/<int:item_id>/legs/add", methods=["POST"])
def add_leg(item_id):
    get_or_404(item_id)
    raw = request.form.get("leg_id", "")
    leg = query_one("SELECT leg_id FROM flight_leg WHERE leg_id = %s", (raw,)) if raw.isdigit() else None
    if leg is None:
        flash("Choose a flight leg that exists.", "error")
    else:
        try:
            execute("INSERT INTO reservation_leg (reservation_id, leg_id) VALUES (%s, %s)",
                    (item_id, leg["leg_id"]))
            flash(f"Flight leg {leg['leg_id']} was added to reservation {item_id}.", "success")
        except IntegrityError as exc:
            if exc.errno == 1062:
                flash(f"Flight leg {leg['leg_id']} is already on this reservation.", "error")
            else:
                raise
    return redirect(url_for("reservations.detail", item_id=item_id))


@bp.route("/<int:item_id>/legs/<int:leg_id>/remove", methods=["POST"])
def remove_leg(item_id, leg_id):
    get_or_404(item_id)
    removed = execute("DELETE FROM reservation_leg WHERE reservation_id = %s AND leg_id = %s",
                      (item_id, leg_id))
    if removed:
        flash(f"Flight leg {leg_id} was removed from the reservation. The leg itself still exists.", "success")
    else:
        flash("That flight leg is not on this reservation.", "error")
    return redirect(url_for("reservations.detail", item_id=item_id))
