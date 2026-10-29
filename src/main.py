"""Rejestr wypożyczeń sprzętu komputerowego (Flask + PostgreSQL)."""
import os
import time
from contextlib import contextmanager
from datetime import date

import psycopg2
from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   url_for)
from psycopg2.extras import RealDictCursor

CATEGORIES = ["laptop", "projektor", "tablet", "kamera", "inne"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS equipment (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(120) NOT NULL,
    category     VARCHAR(40)  NOT NULL,
    inventory_no VARCHAR(40)  NOT NULL UNIQUE,
    status       VARCHAR(20)  NOT NULL DEFAULT 'available'
                 CHECK (status IN ('available', 'loaned')),
    created_at   TIMESTAMP    NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS loans (
    id               SERIAL PRIMARY KEY,
    equipment_id     INTEGER      NOT NULL REFERENCES equipment(id),
    borrower_name    VARCHAR(120) NOT NULL,
    borrower_contact VARCHAR(120),
    loaned_at        TIMESTAMP    NOT NULL DEFAULT now(),
    due_date         DATE,
    returned_at      TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_loan_per_item
    ON loans (equipment_id) WHERE returned_at IS NULL;
"""


def db_params():
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", "rejestr"),
        "user": os.getenv("DB_USER", "rejestr"),
        "password": os.getenv("DB_PASSWORD", "rejestr"),
    }


@contextmanager
def get_conn():
    """Połączenie z bazą; commit po sukcesie, rollback przy błędzie."""
    conn = psycopg2.connect(**db_params())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql, params=()):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def init_db(retries=30, delay=1):
    """Tworzy tabele; czeka aż baza będzie gotowa."""
    for attempt in range(retries):
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(42)")
                cur.execute(SCHEMA)
            return
        except psycopg2.OperationalError:
            if attempt == retries - 1:
                raise
            time.sleep(delay)


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-me")
    init_db()

    @app.route("/health")
    def health():
        try:
            query("SELECT 1")
        except psycopg2.Error:
            return jsonify(status="error"), 503
        return jsonify(status="ok")

    @app.route("/")
    def index():
        status = request.args.get("status")
        if status in ("available", "loaned"):
            items = query("SELECT * FROM equipment WHERE status = %s "
                          "ORDER BY name", (status,))
        else:
            items = query("SELECT * FROM equipment ORDER BY name")
        return render_template("index.html", items=items,
                               categories=CATEGORIES, current=status)

    @app.route("/equipment", methods=["POST"])
    def add_equipment():
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        inventory_no = request.form.get("inventory_no", "").strip()
        if not name or not inventory_no or category not in CATEGORIES:
            flash("Wypełnij nazwę, kategorię i numer inwentarzowy.", "error")
            return redirect(url_for("index"))
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO equipment (name, category, inventory_no) "
                    "VALUES (%s, %s, %s)", (name, category, inventory_no))
        except psycopg2.errors.UniqueViolation:
            flash(f"Numer inwentarzowy {inventory_no} już istnieje.", "error")
            return redirect(url_for("index"))
        flash(f"Dodano sprzęt: {name}.", "ok")
        return redirect(url_for("index"))

    @app.route("/loans")
    def loans():
        active = query(
            "SELECT l.*, e.name, e.inventory_no FROM loans l "
            "JOIN equipment e ON e.id = l.equipment_id "
            "WHERE l.returned_at IS NULL ORDER BY l.loaned_at DESC")
        history = query(
            "SELECT l.*, e.name, e.inventory_no FROM loans l "
            "JOIN equipment e ON e.id = l.equipment_id "
            "WHERE l.returned_at IS NOT NULL "
            "ORDER BY l.returned_at DESC LIMIT 50")
        available = query("SELECT id, name, inventory_no FROM equipment "
                          "WHERE status = 'available' ORDER BY name")
        return render_template("loans.html", active=active, history=history,
                               available=available, today=date.today())

    @app.route("/loans", methods=["POST"])
    def create_loan():
        borrower = request.form.get("borrower_name", "").strip()
        contact = request.form.get("borrower_contact", "").strip() or None
        due_raw = request.form.get("due_date", "").strip()
        try:
            equipment_id = int(request.form.get("equipment_id", ""))
            due = date.fromisoformat(due_raw) if due_raw else None
        except ValueError:
            flash("Nieprawidłowe dane formularza.", "error")
            return redirect(url_for("loans"))
        if not borrower:
            flash("Podaj osobę wypożyczającą.", "error")
            return redirect(url_for("loans"))
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT status FROM equipment WHERE id = %s "
                        "FOR UPDATE", (equipment_id,))
            row = cur.fetchone()
            if row is None:
                flash("Nie ma takiego sprzętu.", "error")
            elif row["status"] != "available":
                flash("Ten sprzęt jest już wypożyczony.", "error")
            else:
                cur.execute(
                    "INSERT INTO loans (equipment_id, borrower_name, "
                    "borrower_contact, due_date) VALUES (%s, %s, %s, %s)",
                    (equipment_id, borrower, contact, due))
                cur.execute("UPDATE equipment SET status = 'loaned' "
                            "WHERE id = %s", (equipment_id,))
                flash(f"Wypożyczono sprzęt osobie: {borrower}.", "ok")
        return redirect(url_for("loans"))

    @app.route("/loans/<int:loan_id>/return", methods=["POST"])
    def return_loan(loan_id):
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT equipment_id FROM loans WHERE id = %s "
                        "AND returned_at IS NULL FOR UPDATE", (loan_id,))
            row = cur.fetchone()
            if row is None:
                flash("Nie znaleziono aktywnego wypożyczenia.", "error")
            else:
                cur.execute("UPDATE loans SET returned_at = now() "
                            "WHERE id = %s", (loan_id,))
                cur.execute("UPDATE equipment SET status = 'available' "
                            "WHERE id = %s", (row["equipment_id"],))
                flash("Zwrot zapisany.", "ok")
        return redirect(url_for("loans"))

    @app.route("/api/equipment")
    def api_equipment():
        rows = query("SELECT id, name, category, inventory_no, status "
                     "FROM equipment ORDER BY id")
        return jsonify(rows)

    return app
