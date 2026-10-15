"""Booking agents CRUD."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from db import execute, query_all, query_one
from routes.helpers import check_text, safe_delete

bp = Blueprint("agents", __name__, url_prefix="/agents")

FIELDS = [
    dict(name="agent_name", label="Agent name", type="text", maxlength=120, required=True),
    dict(name="other_details", label="Other details", type="textarea", maxlength=255),
]
COLUMNS = [f["name"] for f in FIELDS]
LIST_COLUMNS = [("agent_id", "ID"), ("agent_name", "Name"),
                ("other_details", "Details"), ("reservations", "Reservations")]


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
    return errors


def render_form(heading, values):
    return render_template("crud_form.html", heading=heading, fields=FIELDS, values=values,
                           cancel_url=url_for("agents.index"))


def get_or_404(item_id):
    row = query_one("SELECT * FROM booking_agent WHERE agent_id = %s", (item_id,))
    if row is None:
        abort(404)
    return row


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    sql = ("SELECT a.agent_id, a.agent_name, a.other_details, "
           "(SELECT COUNT(*) FROM reservation r WHERE r.agent_id = a.agent_id) AS reservations "
           "FROM booking_agent a")
    params = ()
    if q:
        like = f"%{q}%"
        sql += " WHERE a.agent_name LIKE %s OR a.other_details LIKE %s"
        params = (like, like)
    sql += " ORDER BY a.agent_name LIMIT 200"
    return render_template("crud_list.html", title="Booking agents", singular="agent",
                           rows=query_all(sql, params), columns=LIST_COLUMNS, q=q,
                           placeholder="Search agent name or details",
                           new_url=url_for("agents.create"), id_key="agent_id",
                           edit_endpoint="agents.edit", delete_endpoint="agents.delete")


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        data = clean(request.form)
        errors = validate(data)
        if not errors:
            execute("INSERT INTO booking_agent (agent_name, other_details) VALUES (%s, %s)",
                    (data["agent_name"], data["other_details"]))
            flash("Booking agent was created.", "success")
            return redirect(url_for("agents.index"))
        for message in errors:
            flash(message, "error")
        return render_form("New booking agent", data)
    return render_form("New booking agent", {})


@bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
def edit(item_id):
    row = get_or_404(item_id)
    if request.method == "POST":
        data = clean(request.form)
        errors = validate(data)
        if not errors:
            execute("UPDATE booking_agent SET agent_name = %s, other_details = %s WHERE agent_id = %s",
                    (data["agent_name"], data["other_details"], item_id))
            flash(f"Booking agent {item_id} was updated.", "success")
            return redirect(url_for("agents.index"))
        for message in errors:
            flash(message, "error")
        return render_form(f"Edit booking agent {item_id}", data)
    return render_form(f"Edit booking agent {item_id}", row)


@bp.route("/<int:item_id>/delete", methods=["POST"])
def delete(item_id):
    get_or_404(item_id)
    safe_delete("booking_agent", "agent_id", item_id, f"Booking agent {item_id}", [
        ("reservation(s)", "SELECT COUNT(*) AS n FROM reservation WHERE agent_id = %s"),
    ])
    return redirect(url_for("agents.index"))
