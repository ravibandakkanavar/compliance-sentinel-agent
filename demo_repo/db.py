import sqlite3
from datetime import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    full_name TEXT NOT NULL,
    date_of_birth TEXT,
    ssn TEXT,
    annual_income INTEGER,
    marketing_opt_in INTEGER DEFAULT 1,
    do_not_sell INTEGER DEFAULT 0,
    deleted INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    total_cents INTEGER NOT NULL,
    shipping_address TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    ip_address TEXT,
    path TEXT,
    created_at TEXT NOT NULL
);
"""


def connect():
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)


def create_user(email, password, full_name, date_of_birth, ssn, annual_income, marketing_opt_in):
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO users (email, password, full_name, date_of_birth, ssn, annual_income,"
            " marketing_opt_in, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                email,
                password,
                full_name,
                date_of_birth,
                ssn,
                annual_income,
                marketing_opt_in,
                datetime.utcnow().isoformat(),
            ),
        )
        return cursor.lastrowid


def get_user(user_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_email(email):
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def check_password(user, password):
    return user is not None and user["password"] == password


def mark_deleted(user_id):
    with connect() as conn:
        conn.execute("UPDATE users SET deleted = 1 WHERE id = ?", (user_id,))


def orders_for(user_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM orders WHERE user_id = ?", (user_id,)).fetchall()


def record_access(user_id, ip_address, path):
    with connect() as conn:
        conn.execute(
            "INSERT INTO access_log (user_id, ip_address, path, created_at) VALUES (?, ?, ?, ?)",
            (user_id, ip_address, path, datetime.utcnow().isoformat()),
        )


def all_active_users():
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE deleted = 0").fetchall()
