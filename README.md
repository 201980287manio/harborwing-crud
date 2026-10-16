# HarborWing Air CRUD Application (IT8 Drill 2 / Part 2)

A web application that lets HarborWing Air employees work with the airline database **without writing SQL**. It is built with Python, Flask and `mysql-connector-python`, and it uses the database created in the Midterm Drill (Part 1).

> **Database (Part 1):** `https://github.com/201980287manio/harborwing-db.git`
> **Database version / commit used:** `b7e5bce` (branch `main`)
> **Explainer video:** `<add video link here>`

**No schema changes were made.** The application uses the Part 1 schema and its seed data exactly as they are.

---

## Features

| Area | What you can do |
|---|---|
| Passengers | Search, create, edit, delete |
| Booking agents | Search, create, edit, delete |
| Payments | Search, create, edit, delete |
| Airports | Search, create, edit (code is fixed), delete |
| Flight schedules | Search, create, edit, delete |
| Flight legs | Search, create, edit, delete |
| Flight costs | Search, create, edit, delete (composite key) |
| Reservations | Search, create, edit, delete, and a **complete view** (passenger, agent, legs, payments, total) |
| Reservation payment links | Link an existing payment, **create and link** a payment in one transaction, remove a link |
| Reservation leg links | Add a leg, remove a leg link |
| Calendar and reference codes | Read-only pages (these are maintained by the Part 1 seed script) |

Behaviour that is built in:

- Success and error messages on every action.
- Missing records show a "Not found" page instead of crashing.
- Duplicate links are blocked and explained.
- Removing a link **never deletes** the payment or leg itself.
- Deleting a record that other records still use is refused with a clear explanation.
- The dashboard shows live row counts for all 11 tables.

---

## Installation and setup

**Requirements:** Python 3.10+, MySQL 8 (or MariaDB 10.5+), Git. This project was developed with XAMPP, where MySQL runs on port **3307**.

### 1. Set up the database from Part 1
Follow the README in the Part 1 repository (linked above). In short:

1. Create an empty database named `harborwing_air`.
2. Run `database/01_schema.sql` against it.
3. Run the seed script (`python seed.py` in the Part 1 `seed/` folder) to fill every table with synthetic data.

Check that the dashboard of this app later shows at least 50 rows for every table.

### 2. Get this application
```
git clone <this repository's URL>
cd harborwing-crud
```

### 3. Install dependencies
```
python -m venv venv
venv\Scripts\activate          (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
```

### 4. Configure the database connection
Copy the example settings file and edit it:
```
copy .env.example .env         (macOS/Linux: cp .env.example .env)
```

| Setting | Meaning | Example |
|---|---|---|
| `DB_HOST` | MySQL host | `127.0.0.1` |
| `DB_PORT` | MySQL port | `3307` (XAMPP here) or `3306` |
| `DB_USER` | MySQL user | `root` |
| `DB_PASSWORD` | MySQL password | empty for default XAMPP |
| `DB_NAME` | Database name | `harborwing_air` |
| `SECRET_KEY` | Any random text (used for flash messages) | `change-me` |

`.env` is listed in `.gitignore`, so **credentials are never committed**. Only `.env.example` (no secrets) is in the repository.

### 5. Start the application
Make sure MySQL is running, then:
```
python app.py
```
Open **http://127.0.0.1:5000**. Stop the app with `Ctrl + C`.

---

## How to perform CRUD operations

1. Use the navigation bar to open a module (Reservations, Passengers, Agents, Payments, Airports, Schedules, Legs, Costs, Calendar, Codes).
2. **Read / search:** every list has a search box; type text and press Search. Reservations and several lists show how many related records each row has.
3. **Create:** click **+ New ...**, fill in the form, and press Save. Invalid input shows messages and keeps what you typed.
4. **Update:** click **Edit** on a row, change the fields, and press Save. Keys (airport code, flight number, cost key) cannot be changed.
5. **Delete:** click **Delete** and confirm. If the record is still in use, the app explains why it was not deleted.
6. **Full reservation:** in Reservations, click **View**. From there you can add or remove legs, link or unlink payments, or create and link a new payment.

### Required workflow (as demonstrated in the video)
1. Create a passenger.
2. Create a reservation for that passenger.
3. Add two flight legs on the reservation page.
4. Create and link a payment.
5. View the complete reservation.
6. Update a record (for example the reservation status).
7. Remove a payment or leg link; the payment or leg still exists afterwards.
8. Safely delete an eligible record.
9. Attempt an invalid operation (for example linking the same leg twice) and see the error message.

---

## How the application works

### Project structure
```
app.py                  Creates the Flask app, registers the modules, handles errors
db.py                   Database connection and query/transaction helpers
routes/
    helpers.py          Shared validation and the safe_delete() function
    passengers.py ...   One module per entity (agents, payments, airports,
    schedules.py ...    schedules, legs, costs), plus reservations.py and reference.py
templates/              HTML pages (Jinja). crud_list.html and crud_form.html are shared
static/style.css        Styling
```

### How a user action becomes a database query
Every action follows the same path: **browser form → Flask route → validation → `db.py` helper → SQL with placeholders → MySQL → message → redirect.**

Example: the user clicks **Add flight leg** on reservation 12 and picks leg 5.

1. The browser sends `POST /reservations/12/legs/add` with `leg_id=5`.
2. The route `add_leg()` in `routes/reservations.py` runs. It first checks that reservation 12 exists (otherwise the "Not found" page is shown).
3. It validates the input and checks the leg exists:
   ```python
   leg = query_one("SELECT leg_id FROM flight_leg WHERE leg_id = %s", (raw,))
   ```
4. It inserts the link, with values passed separately from the SQL text:
   ```python
   execute("INSERT INTO reservation_leg (reservation_id, leg_id) VALUES (%s, %s)",
           (item_id, leg["leg_id"]))
   ```
5. `execute()` in `db.py` runs the statement, **commits** on success, and **rolls back** on any error.
6. If the pair already exists, MySQL raises error 1062 (the composite primary key). The route catches it and shows "Flight leg 5 is already on this reservation."
7. The route redirects back to the reservation page, which shows the flash message and the updated list.

### Database access rules
- **Parameterized queries only.** Every value goes through `%s` placeholders. The only text placed inside SQL strings is fixed table and column names written in the code, never user input.
- **Configurable connection.** Settings are read from environment variables (`.env`), so no credentials are in the source code.
- **One connection per request**, closed automatically when the request ends.
- **Validation before SQL.** Required fields, lengths, formats, positive amounts, date order, different origin and destination, and valid dropdown choices are checked first, and understandable messages are shown.

### Transactions
`db.py` provides three ways to write:

| Helper | Used for |
|---|---|
| `execute()` | One statement, committed or rolled back |
| `run_transaction()` | A fixed list of statements as one transaction |
| `transaction()` | A `with` block as one transaction, when a later step needs the id from an earlier one (`cursor.lastrowid`) |

Where several tables change together, one transaction is used:

- **Create and link a payment** (`reservations.new_payment`): inserts the payment, then links it to the reservation. If the link fails, the payment is not created either.
- **Create a reservation** (`reservations.create`): inserts the reservation and reads the new id inside one transaction.
- **Edit a flight schedule** (`schedules.edit`): updates the schedule and the origin/destination copied into its legs, so the two tables cannot disagree.

### Foreign-key integrity and deletion policy
The database enforces the Part 1 rules (foreign keys, CHECK constraints, composite keys, InnoDB). The application adds friendly handling on top:

| Action | Policy |
|---|---|
| Delete a passenger or agent used by reservations | Refused, with the number of reservations |
| Delete an airport used by schedules or legs | Refused, with the counts |
| Delete a schedule that has legs or costs | Refused, with the counts |
| Delete a leg or payment linked to reservations | Refused; remove the links first |
| Remove a payment or leg **link** | Deletes only the link row; the payment/leg is kept |
| Delete a reservation | Allowed; its link rows are removed (`ON DELETE CASCADE`); payments and legs are kept |

`safe_delete()` in `routes/helpers.py` counts what still references a record before deleting, and it also catches MySQL error 1451 (foreign key still referenced) as a safety net.

### Avoiding inflated payment totals
The reservation page loads payments and legs with **separate queries**, and the total is summed over payments only. Joining payments and legs in one query would repeat every payment once per leg and inflate the total.

### Other design decisions
- A **flight leg's** origin and destination are copied from its flight schedule, so they cannot disagree.
- **Flight costs** are identified by flight number, aircraft type and valid-from date (the composite key). In URLs they are written `FLIGHT~AIRCRAFT~DATE`. The application rejects a cost period that **overlaps** another period for the same flight and aircraft type (the overlap policy that Part 1 left open).
- Times are entered and shown as **UTC**.

---

## Known limitations

- **Shared payments:** the database does not store how much of a payment belongs to each reservation, so a shared payment is shown at its full amount on every reservation that uses it. Party size does not identify every traveler.
- **Reference codes** (airline, aircraft type, statuses, ticket types, travel classes) are externally managed. The dropdown values for statuses, ticket types and classes are fixed lists in the code and match the demonstration values in the seed data.
- **Calendar and reference records** are read-only in the app; they are maintained by the Part 1 seed script.
- **No login or user roles.** Anyone who can open the site can change data. A real system would add authentication.
- **No CSRF protection** on forms, and the app runs with Flask's development server (`debug=True`). Both should change before any real deployment.
- Lists show at most 200 to 400 rows and have no paging; use the search box to narrow them.
- The overlap check for flight costs happens in the application, not in the database, so edits made directly in SQL could still create overlapping periods.
- Linking is done one leg or payment at a time.
- The app was tested manually through the browser; there are no automated tests.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Database error" page | MySQL is not running, or `.env` has the wrong host, port, user, password or database name |
| `python` or modules not found | Activate the virtual environment first (`venv\Scripts\activate`) |
| "Unknown database" | Create `harborwing_air` and run the Part 1 schema and seed first |
| Port 5000 already in use | Close the other running copy of the app |
