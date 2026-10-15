"""Shared helpers for the CRUD modules."""
from datetime import datetime

from flask import flash
from mysql.connector import IntegrityError

from db import execute, query_one


def check_text(errors, value, label, limit, required=False):
    """Append a readable message to `errors` if the value is missing or too long."""
    if not value:
        if required:
            errors.append(f"{label} is required.")
    elif len(value) > limit:
        errors.append(f"{label} must be at most {limit} characters.")


def safe_delete(table, id_column, item_id, label, usage_checks):
    """Delete one row only if nothing references it.

    usage_checks: list of (description, count_sql). Each count_sql takes the id
    as its only parameter and returns a column named n. If any count is above
    zero the delete is refused with a clear explanation (our deletion policy is
    RESTRICT). The IntegrityError handler is a safety net for the database's own
    foreign-key rule. Table and column names are fixed constants in the calling
    code, never user input; the id is always a bound parameter.
    Returns True if the row was deleted.
    """
    blockers = []
    for description, sql in usage_checks:
        n = query_one(sql, (item_id,))["n"]
        if n:
            blockers.append(f"{n} {description}")
    if blockers:
        flash(f"{label} cannot be deleted: it is used by " + " and ".join(blockers) + ".", "error")
        return False
    try:
        execute(f"DELETE FROM {table} WHERE {id_column} = %s", (item_id,))
    except IntegrityError as exc:
        if exc.errno == 1451:  # foreign key still references the row
            flash(f"{label} is still referenced by other records and was not deleted.", "error")
            return False
        raise
    flash(f"{label} was deleted.", "success")
    return True


def parse_datetime(raw):
    """'2026-10-01T14:30' -> datetime. Empty text -> None. Bad text -> ValueError."""
    raw = (raw or "").strip()
    return datetime.fromisoformat(raw) if raw else None


def datetime_input(value):
    """datetime -> text for an <input type="datetime-local"> (empty if None)."""
    return value.strftime("%Y-%m-%dT%H:%M") if value else ""
