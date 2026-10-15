"""Database access for the HarborWing CRUD app.

Connection settings come from environment variables (loaded from .env),
so no credentials live in source code. Every query uses %s placeholders
(parameterized queries) so user input is never pasted into SQL text.
"""
import os

import mysql.connector
from dotenv import load_dotenv
from flask import g

load_dotenv()


def get_db():
    """One connection per request, created on first use."""
    if "db" not in g:
        g.db = mysql.connector.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "harborwing_air"),
            autocommit=False,
        )
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_all(sql, params=()):
    cur = get_db().cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()


def query_one(sql, params=()):
    rows = query_all(sql, params)
    return rows[0] if rows else None


def execute(sql, params=()):
    """Run one INSERT/UPDATE/DELETE in its own transaction.
    Commits on success, rolls back and re-raises on any error."""
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(sql, params)
        db.commit()
        return cur.rowcount
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()


def run_transaction(statements):
    """Run several statements as ONE transaction: all succeed or none do.

    statements: list of (sql, params). If any statement fails, everything is
    rolled back, so related tables never end up half-updated.
    """
    db = get_db()
    cur = db.cursor()
    try:
        for sql, params in statements:
            cur.execute(sql, params)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()
