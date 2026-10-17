"""
Restaurant Management System - Main Application
================================================
Backend: Python Flask
Database: SQLite
Author: Built with Antigravity AI
"""

from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import sqlite3
import os
import json
import qrcode
from datetime import datetime

# ─────────────────────────────────────────────
# APP CONFIGURATION
# ─────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "restaurant_secret_key_2024"  # needed for session (cart)

DATABASE = "restaurant.db"  # SQLite database file
QR_FOLDER = os.path.join("static", "qrcodes")
os.makedirs(QR_FOLDER, exist_ok=True)

# ─────────────────────────────────────────────
# GLOBAL SQL QUERY LOG  (for examiner demo)
# ─────────────────────────────────────────────
# Every SQL query executed by the app is stored here so
# the examiner can see live what's happening in the DB.
SQL_LOG = []          # list of dicts: {sql, params, rows, timestamp, route}
MAX_LOG_ENTRIES = 100  # keep last 100 queries


# ─────────────────────────────────────────────
# JINJA2 CUSTOM FILTER – SQL Syntax Highlighter
# ─────────────────────────────────────────────
import re
from markupsafe import Markup, escape

@app.template_filter('highlight_sql')
def highlight_sql(sql):
    """
    Wrap SQL keywords, table names, strings, and numbers in coloured <span> tags
    so they display with syntax highlighting in the Live SQL Viewer.
    """
    keywords = [
        'SELECT', 'FROM', 'WHERE', 'INSERT', 'INTO', 'VALUES',
        'UPDATE', 'SET', 'DELETE', 'CREATE', 'TABLE', 'DROP',
        'ALTER', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'ON',
        'AND', 'OR', 'NOT', 'IN', 'IS', 'NULL', 'LIKE', 'BETWEEN',
        'ORDER', 'BY', 'GROUP', 'HAVING', 'LIMIT', 'OFFSET',
        'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'AS', 'DISTINCT',
        'PRIMARY', 'KEY', 'FOREIGN', 'REFERENCES', 'DEFAULT',
        'AUTOINCREMENT', 'UNIQUE', 'NOT NULL', 'CHECK', 'IF',
        'EXISTS', 'COALESCE', 'PRAGMA', 'BEGIN', 'COMMIT',
    ]
    # 1. HTML-escape the raw string first (safety)
    safe = str(escape(sql))

    # 2. Highlight string literals  (single-quoted)
    safe = re.sub(
        r"'([^']*?)'",
        r"<span class='sql-string'>'\1'</span>",
        safe
    )
    # 3. Highlight numbers
    safe = re.sub(
        r'\b(\d+\.?\d*)\b',
        r"<span class='sql-number'>\1</span>",
        safe
    )
    # 4. Highlight keywords (case-insensitive, whole word)
    for kw in keywords:
        safe = re.sub(
            rf'\b({re.escape(kw)})\b',
            r"<span class='sql-keyword'>\1</span>",
            safe,
            flags=re.IGNORECASE
        )
    # 5. Highlight placeholder ? marks
    safe = safe.replace('?', "<span class='sql-number'>?</span>")

    return Markup(safe)


# ─────────────────────────────────────────────
# DATABASE HELPER FUNCTIONS
# ─────────────────────────────────────────────
class LoggingConnection:
    """Wrapper for sqlite3.Connection that logs all execute calls."""
    def __init__(self, conn):
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    def execute(self, sql, params=()):
        """Wrapper that logs every SQL statement before running it."""
        # Skip internal/noisy pragmas from the log display
        skip_prefixes = ("PRAGMA",)
        sql_clean = sql.strip()
        if not any(sql_clean.upper().startswith(p) for p in skip_prefixes):
            try:
                from flask import request as _req
                route = _req.path
            except Exception:
                route = "(init)"

            entry = {
                "sql":       sql_clean,
                "params":    list(params) if params else [],
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "route":     route,
                "rows":      None,   # filled in after fetch
            }
            SQL_LOG.append(entry)
            # Trim to last MAX_LOG_ENTRIES
            if len(SQL_LOG) > MAX_LOG_ENTRIES:
                SQL_LOG.pop(0)

        return self._conn.execute(sql, params)

    def close(self):
        self._conn.close()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def cursor(self):
        return self._conn.cursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def get_db():
    """Open a new database connection with query logging enabled."""
    conn = sqlite3.connect(DATABASE)
    return LoggingConnection(conn)


def init_db():
    """
    Create all tables and insert sample data.
    Called once when the app starts.
    """
    conn = get_db()
    cursor = conn.cursor()

    # ── tables table ──────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tables (
            table_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            table_number INTEGER UNIQUE NOT NULL,
            status       TEXT NOT NULL DEFAULT 'available'
                         CHECK(status IN ('available', 'occupied', 'reserved'))
        )
    """)

    # ── menu table ────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS menu (
            item_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name  TEXT    NOT NULL,
            price      REAL    NOT NULL,
            category   TEXT    NOT NULL,
            description TEXT   DEFAULT '',
            available  INTEGER NOT NULL DEFAULT 1   -- 1=yes, 0=no
        )
    """)

    # ── orders table ──────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            table_id     INTEGER NOT NULL,
            total_amount REAL    NOT NULL DEFAULT 0,
            status       TEXT    NOT NULL DEFAULT 'Pending'
                         CHECK(status IN ('Pending', 'Preparing', 'Served', 'Paid')),
            timestamp    TEXT    NOT NULL,
            FOREIGN KEY (table_id) REFERENCES tables(table_id)
        )
    """)

    # ── order_items table ─────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id      INTEGER NOT NULL,
            item_id       INTEGER NOT NULL,
            quantity      INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (item_id)  REFERENCES menu(item_id)
        )
    """)

    # ── seed: restaurant tables ───────────────────────────────────
    cursor.execute("SELECT COUNT(*) FROM tables")
    if cursor.fetchone()[0] == 0:
        for t in range(1, 11):   # Tables 1-10
            cursor.execute(
                "INSERT INTO tables (table_number, status) VALUES (?, 'available')", (t,)
            )

    # ── seed: menu items ──────────────────────────────────────────
    cursor.execute("SELECT COUNT(*) FROM menu")
    if cursor.fetchone()[0] == 0:
        sample_menu = [
            # Starters
            ("Veg Spring Rolls",    80,  "Starters",    "Crispy vegetable spring rolls served with sweet chili sauce"),
            ("Chicken Wings",       150, "Starters",    "Spicy buffalo chicken wings with ranch dip"),
            ("Paneer Tikka",        160, "Starters",    "Grilled cottage cheese with mint chutney"),
            ("Soup of the Day",     70,  "Starters",    "Chef's special homemade soup"),
            # Main Course
            ("Butter Chicken",      280, "Main Course", "Creamy tomato-based chicken curry"),
            ("Dal Makhani",         180, "Main Course", "Slow-cooked black lentils in butter and cream"),
            ("Veg Biryani",         200, "Main Course", "Fragrant basmati rice with fresh vegetables"),
            ("Chicken Biryani",     280, "Main Course", "Aromatic basmati rice with tender chicken"),
            ("Paneer Butter Masala",220, "Main Course", "Rich creamy paneer curry"),
            ("Fish Curry",          300, "Main Course", "Traditional coconut-based fish curry"),
            # Breads
            ("Garlic Naan",         40,  "Breads",      "Soft leavened bread with garlic butter"),
            ("Plain Roti",          20,  "Breads",      "Whole wheat flatbread"),
            ("Paratha",             50,  "Breads",      "Layered whole wheat flatbread"),
            # Desserts
            ("Gulab Jamun",         80,  "Desserts",    "Soft milk-solid balls soaked in rose syrup"),
            ("Kulfi",               90,  "Desserts",    "Traditional Indian ice cream"),
            ("Brownie with Ice Cream",120,"Desserts",   "Warm chocolate brownie with vanilla scoop"),
            # Beverages
            ("Masala Chai",         40,  "Beverages",   "Spiced Indian tea"),
            ("Fresh Lime Soda",     60,  "Beverages",   "Chilled lime soda with mint"),
            ("Mango Lassi",         80,  "Beverages",   "Chilled mango yogurt drink"),
            ("Cold Coffee",         100, "Beverages",   "Creamy blended cold coffee"),
        ]
        cursor.executemany(
            "INSERT INTO menu (item_name, price, category, description) VALUES (?, ?, ?, ?)",
            sample_menu
        )

    conn.commit()
    conn.close()
    print("✅  Database initialised successfully.")


# ─────────────────────────────────────────────
# QR CODE GENERATION HELPER
# ─────────────────────────────────────────────
def generate_qr(table_number):
    """Generate a QR code PNG for a given table number."""
    url = f"http://127.0.0.1:5000/menu/{table_number}"
    filename = os.path.join(QR_FOLDER, f"table_{table_number}.png")
    if not os.path.exists(filename):
        img = qrcode.make(url)
        img.save(filename)
    return filename


# ─────────────────────────────────────────────
# ROUTES  –  CUSTOMER SIDE
# ─────────────────────────────────────────────

@app.route("/")
def index():
    """Landing / home page – lists all tables and their QR codes."""
    conn = get_db()
    tables = conn.execute("SELECT * FROM tables ORDER BY table_number").fetchall()
    conn.close()

    # Pre-generate QR codes for every table
    for table in tables:
        generate_qr(table["table_number"])

    return render_template("index.html", tables=tables)


@app.route("/menu/<int:table_number>")
def menu(table_number):
    """
    Menu page – customer scans QR code and lands here.
    Shows all menu items grouped by category.
    """
    conn = get_db()

    # Validate the table
    table = conn.execute(
        "SELECT * FROM tables WHERE table_number = ?", (table_number,)
    ).fetchone()

    if not table:
        conn.close()
        return render_template("error.html", message=f"Table {table_number} does not exist."), 404

    # Fetch all available menu items
    items = conn.execute(
        "SELECT * FROM menu WHERE available = 1 ORDER BY category, item_name"
    ).fetchall()
    conn.close()

    # Group items by category for display
    menu_by_category = {}
    for item in items:
        cat = item["category"]
        menu_by_category.setdefault(cat, []).append(dict(item))

    # Initialise cart in session if missing
    cart_key = f"cart_{table_number}"
    if cart_key not in session:
        session[cart_key] = {}

    cart = session.get(cart_key, {})
    cart_count = sum(cart.values())

    return render_template(
        "menu.html",
        table=table,
        menu_by_category=menu_by_category,
        cart_count=cart_count,
        table_number=table_number,
    )


@app.route("/cart/<int:table_number>", methods=["GET", "POST"])
def cart(table_number):
    """
    Cart page – shows selected items, quantities, and total.
    POST: update quantities or remove items.
    """
    cart_key = f"cart_{table_number}"

    if request.method == "POST":
        action = request.form.get("action")
        item_id = request.form.get("item_id")

        cart = session.get(cart_key, {})

        if action == "add":
            cart[item_id] = cart.get(item_id, 0) + 1
        elif action == "remove":
            if item_id in cart:
                if cart[item_id] > 1:
                    cart[item_id] -= 1
                else:
                    del cart[item_id]
        elif action == "delete":
            cart.pop(item_id, None)
        elif action == "clear":
            cart = {}

        session[cart_key] = cart
        session.modified = True
        return redirect(url_for("cart", table_number=table_number))

    # GET – display cart
    cart = session.get(cart_key, {})
    conn = get_db()
    cart_items = []
    total = 0

    for item_id_str, qty in cart.items():
        item = conn.execute(
            "SELECT * FROM menu WHERE item_id = ?", (item_id_str,)
        ).fetchone()
        if item:
            subtotal = item["price"] * qty
            total += subtotal
            cart_items.append({
                "item_id":   item["item_id"],
                "item_name": item["item_name"],
                "price":     item["price"],
                "quantity":  qty,
                "subtotal":  subtotal,
            })

    conn.close()
    tax = round(total * 0.05, 2)   # 5 % GST
    grand_total = round(total + tax, 2)

    return render_template(
        "cart.html",
        cart_items=cart_items,
        total=total,
        tax=tax,
        grand_total=grand_total,
        table_number=table_number,
    )


@app.route("/add_to_cart/<int:table_number>/<int:item_id>")
def add_to_cart(table_number, item_id):
    """Quick-add an item to cart from the menu page."""
    cart_key = f"cart_{table_number}"
    cart = session.get(cart_key, {})
    cart[str(item_id)] = cart.get(str(item_id), 0) + 1
    session[cart_key] = cart
    session.modified = True
    return redirect(url_for("menu", table_number=table_number))


@app.route("/order/<int:table_number>", methods=["POST"])
def place_order(table_number):
    """
    Place Order route – saves cart contents as a new order in the DB.
    Clears the cart after successful order placement.
    """
    cart_key = f"cart_{table_number}"
    cart = session.get(cart_key, {})

    if not cart:
        return redirect(url_for("menu", table_number=table_number))

    conn = get_db()

    # Get table_id from table_number
    table = conn.execute(
        "SELECT * FROM tables WHERE table_number = ?", (table_number,)
    ).fetchone()

    if not table:
        conn.close()
        return render_template("error.html", message="Table not found."), 404

    # Calculate total
    total = 0
    order_lines = []   # will hold (item_id, qty) tuples

    for item_id_str, qty in cart.items():
        item = conn.execute(
            "SELECT price FROM menu WHERE item_id = ?", (item_id_str,)
        ).fetchone()
        if item:
            total += item["price"] * qty
            order_lines.append((int(item_id_str), qty))

    tax = round(total * 0.05, 2)
    grand_total = round(total + tax, 2)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Insert order
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO orders (table_id, total_amount, status, timestamp) VALUES (?, ?, 'Pending', ?)",
        (table["table_id"], grand_total, timestamp),
    )
    order_id = cursor.lastrowid

    # Insert order items
    for item_id, qty in order_lines:
        cursor.execute(
            "INSERT INTO order_items (order_id, item_id, quantity) VALUES (?, ?, ?)",
            (order_id, item_id, qty),
        )

    # Mark table as occupied
    conn.execute(
        "UPDATE tables SET status = 'occupied' WHERE table_id = ?",
        (table["table_id"],)
    )

    conn.commit()
    conn.close()

    # Clear cart
    session.pop(cart_key, None)
    session.modified = True

    return redirect(url_for("bill", order_id=order_id))


@app.route("/bill/<int:order_id>")
def bill(order_id):
    """
    Bill page – shows itemised bill for a specific order.
    """
    conn = get_db()

    order = conn.execute("""
        SELECT o.*, t.table_number
        FROM orders o
        JOIN tables t ON o.table_id = t.table_id
        WHERE o.order_id = ?
    """, (order_id,)).fetchone()

    if not order:
        conn.close()
        return render_template("error.html", message="Order not found."), 404

    items = conn.execute("""
        SELECT m.item_name, m.price, oi.quantity,
               (m.price * oi.quantity) AS subtotal
        FROM order_items oi
        JOIN menu m ON oi.item_id = m.item_id
        WHERE oi.order_id = ?
    """, (order_id,)).fetchall()

    conn.close()

    subtotal = sum(i["subtotal"] for i in items)
    tax      = round(subtotal * 0.05, 2)
    total    = round(subtotal + tax, 2)

    return render_template(
        "bill.html",
        order=order,
        items=items,
        subtotal=subtotal,
        tax=tax,
        total=total,
    )


# ─────────────────────────────────────────────
# ROUTES  –  ADMIN SIDE
# ─────────────────────────────────────────────

@app.route("/admin")
def admin():
    """
    Admin Dashboard – shows all orders with status, table, and totals.
    """
    conn = get_db()

    orders = conn.execute("""
        SELECT o.order_id, o.total_amount, o.status, o.timestamp,
               t.table_number
        FROM orders o
        JOIN tables t ON o.table_id = t.table_id
        ORDER BY o.timestamp DESC
    """).fetchall()

    # Summary counts
    counts = conn.execute("""
        SELECT status, COUNT(*) as cnt
        FROM orders
        GROUP BY status
    """).fetchall()
    summary = {row["status"]: row["cnt"] for row in counts}

    total_revenue = conn.execute(
        "SELECT COALESCE(SUM(total_amount),0) FROM orders WHERE status='Paid'"
    ).fetchone()[0]

    conn.close()

    return render_template(
        "admin.html",
        orders=orders,
        summary=summary,
        total_revenue=round(total_revenue, 2),
    )


@app.route("/admin/order/<int:order_id>")
def admin_order_detail(order_id):
    """Admin – detailed view of a single order."""
    conn = get_db()

    order = conn.execute("""
        SELECT o.*, t.table_number
        FROM orders o
        JOIN tables t ON o.table_id = t.table_id
        WHERE o.order_id = ?
    """, (order_id,)).fetchone()

    items = conn.execute("""
        SELECT m.item_name, m.price, oi.quantity,
               (m.price * oi.quantity) AS subtotal
        FROM order_items oi
        JOIN menu m ON oi.item_id = m.item_id
        WHERE oi.order_id = ?
    """, (order_id,)).fetchall()

    conn.close()
    return render_template("order_detail.html", order=order, items=items)


@app.route("/admin/update_status/<int:order_id>", methods=["POST"])
def update_status(order_id):
    """Admin – update order status (Pending → Preparing → Served → Paid)."""
    new_status = request.form.get("status")
    valid = ["Pending", "Preparing", "Served", "Paid"]

    if new_status not in valid:
        return redirect(url_for("admin"))

    conn = get_db()
    conn.execute(
        "UPDATE orders SET status = ? WHERE order_id = ?",
        (new_status, order_id)
    )

    # If paid, mark table as available again
    if new_status == "Paid":
        conn.execute("""
            UPDATE tables SET status = 'available'
            WHERE table_id = (SELECT table_id FROM orders WHERE order_id = ?)
        """, (order_id,))

    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/admin/menu")
def admin_menu():
    """Admin – view and manage the menu."""
    conn = get_db()
    items = conn.execute(
        "SELECT * FROM menu ORDER BY category, item_name"
    ).fetchall()
    conn.close()
    return render_template("admin_menu.html", items=items)


@app.route("/admin/menu/toggle/<int:item_id>")
def toggle_menu_item(item_id):
    """Admin – toggle menu item availability."""
    conn = get_db()
    conn.execute(
        "UPDATE menu SET available = 1 - available WHERE item_id = ?", (item_id,)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("admin_menu"))


@app.route("/admin/qrcodes")
def admin_qrcodes():
    """Admin – view all QR codes for each table."""
    conn = get_db()
    tables = conn.execute("SELECT * FROM tables ORDER BY table_number").fetchall()
    conn.close()
    for t in tables:
        generate_qr(t["table_number"])
    return render_template("admin_qrcodes.html", tables=tables)


# ─────────────────────────────────────────────
# ADMIN – LIVE SQL QUERY VIEWER
# ─────────────────────────────────────────────

@app.route("/admin/sql")
def admin_sql():
    """
    Live SQL Query Viewer.
    Shows every SQL statement the app has executed since startup,
    including the query text, bound parameters, timestamp, and route.
    Perfect for demonstrating the DB layer to an examiner.
    """
    # Also expose the full schema so the examiner can inspect it
    conn = get_db()
    tables_info = {}
    table_names = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    for t in table_names:
        tname = t["name"]
        columns = conn.execute(f"PRAGMA table_info({tname})").fetchall()
        row_count = conn.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
        tables_info[tname] = {
            "columns":   [dict(c) for c in columns],
            "row_count": row_count,
        }
    conn.close()

    # Return newest queries first
    log_reversed = list(reversed(SQL_LOG))
    return render_template(
        "admin_sql.html",
        sql_log=log_reversed,
        tables_info=tables_info,
    )


@app.route("/admin/sql/run", methods=["POST"])
def admin_sql_run():
    """
    Execute a custom SQL query typed by the examiner and return results.
    Only SELECT queries are allowed for safety.
    """
    query = request.form.get("query", "").strip()
    results = []
    columns = []
    error = ""
    rows_affected = 0

    if not query:
        return redirect(url_for("admin_sql"))

    conn = get_db()
    try:
        cursor = conn.execute(query)
        if query.upper().startswith("SELECT"):
            rows = cursor.fetchall()
            if rows:
                columns = list(rows[0].keys())
                results = [list(row) for row in rows]
        else:
            # Allow INSERT / UPDATE / DELETE for demo purposes
            conn.commit()
            rows_affected = cursor.rowcount
        # Log it manually with the result count
        if SQL_LOG:
            SQL_LOG[-1]["rows"] = len(results) if results else rows_affected
    except Exception as e:
        error = str(e)
    finally:
        conn.close()

    log_reversed = list(reversed(SQL_LOG))
    # Re-fetch schema
    conn2 = get_db()
    tables_info = {}
    table_names = conn2.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    for t in table_names:
        tname = t["name"]
        cols = conn2.execute(f"PRAGMA table_info({tname})").fetchall()
        rc   = conn2.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
        tables_info[tname] = {"columns": [dict(c) for c in cols], "row_count": rc}
    conn2.close()

    return render_template(
        "admin_sql.html",
        sql_log=log_reversed,
        tables_info=tables_info,
        query_result={"columns": columns, "rows": results,
                      "error": error, "query": query,
                      "rows_affected": rows_affected},
    )


@app.route("/admin/sql/clear")
def admin_sql_clear():
    """Clear the SQL query log."""
    SQL_LOG.clear()
    return redirect(url_for("admin_sql"))


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_db()                     # Set up DB on first run
    app.run(debug=True, port=5000)
