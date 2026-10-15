"""HarborWing Air CRUD application (IT8 Drill 2).

Run:  python app.py      then open http://127.0.0.1:5000
"""
import os

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, render_template

load_dotenv()

from db import close_db, query_one  # noqa: E402
from routes import (agents, airports, costs, legs, passengers,  # noqa: E402
                    payments, schedules)

# Table names are fixed here (never taken from user input).
TABLES = [
    "booking_agent", "passenger", "airport", "calendar_date",
    "flight_schedule", "flight_leg", "flight_cost",
    "reservation", "payment", "reservation_payment", "reservation_leg",
]


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "dev-only-change-me")
    app.teardown_appcontext(close_db)
    for module in (airports, passengers, agents, payments, schedules, legs, costs):
        app.register_blueprint(module.bp)

    @app.route("/")
    def index():
        counts = {t: query_one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in TABLES}
        return render_template("index.html", counts=counts)

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", title="Not found",
                               message="That page or record does not exist."), 404

    @app.errorhandler(mysql.connector.Error)
    def database_error(e):
        app.logger.error("Database error: %s", e)
        return render_template(
            "error.html", title="Database error",
            message="The database could not complete the request. "
                    "Check that MySQL is running and the settings in .env are correct."), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
