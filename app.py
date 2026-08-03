"""
Library Management System - Flask Application
Refactored: duplicate routes/functions merged, bugs fixed, security hardened.
All routes, templates, and database tables/columns are unchanged.
"""
import os
from dotenv import load_dotenv

load_dotenv()

import os
from datetime import date, timedelta
from functools import wraps


from flask import send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle
)
import io
from datetime import datetime

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import mysql.connector
from flask import Flask, render_template, request, redirect, flash, session
from werkzeug.security import generate_password_hash, check_password_hash

# =========================================================
# App Configuration
# =========================================================

app = Flask(__name__)

# Secret key / DB credentials pulled from environment variables where possible.
# Fallbacks preserve original behavior for local/dev use, but should be
# replaced with real secrets via environment variables in production.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "library_secret_key")

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME"),
}

# Standard loan period (in days) applied when a book is borrowed, and how
# many days out a "due soon" notification should start warning a student.
DEFAULT_LOAN_DAYS = 14
DUE_SOON_WINDOW_DAYS = 3

# Email (SMTP) configuration for due-date reminder emails. All pulled from
# environment variables; email sending is silently disabled if SMTP_HOST
# isn't configured, so the app keeps working fine without it.
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() != "false"
SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", SMTP_USERNAME)
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Central Library")
EMAIL_NOTIFICATIONS_ENABLED = bool(SMTP_HOST and SMTP_FROM_EMAIL)

# =========================================================
# Database Connection
# =========================================================

db = mysql.connector.connect(**DB_CONFIG)

# This app uses a single long-lived connection shared across every request
# (rather than one connection per request). Without autocommit, MySQL's
# default REPEATABLE READ isolation means a read-only page (e.g. a
# dashboard) can keep seeing an old "snapshot" of the data until some
# other query happens to commit - which can make counts (borrowed books,
# overdue books, etc.) look stuck/stale even after the underlying data
# has changed. Autocommit makes every statement see the latest committed
# data immediately, which is what a simple CRUD app like this wants.
db.autocommit = True

cursor = db.cursor()


# =========================================================
# Decorators (replace repeated session/role checks)
# =========================================================

def login_required(f):
    """Require an active admin session for a route."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        if "admin" not in session:
            return redirect("/login")
        return f(*args, **kwargs)

    return wrapper


def role_required(*allowed_roles):
    """Require an active admin session AND one of the allowed roles."""

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "admin" not in session:
                return redirect("/login")
            if session.get("role") not in allowed_roles:
                flash("Access Denied!", "danger")
                return redirect("/dashboard")
            return f(*args, **kwargs)

        return wrapper

    return decorator

def student_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):

        if "student_id" not in session:
            flash("Please login to continue.", "warning")
            return redirect("/student_login")

        return f(*args, **kwargs)

    return wrapper


# =========================================================
# Helper Functions
# =========================================================

def create_pdf(title, headers, data):
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(buffer, pagesize=A4)

    styles = getSampleStyleSheet()

    elements = []

    elements.append(
        Paragraph(
            "<b>UTTAR BHARATIYA SANGH'S</b>",
            styles["Title"]
        )
    )

    elements.append(
        Paragraph(
            "<b>MAHENDRA PRATAP SHARADA PRASAD SINGH</b>",
            styles["Heading1"]
        )
    )

    elements.append(
        Paragraph(
            "<b>COLLEGE OF COMMERCE AND SCIENCE</b>",
            styles["Heading2"]
        )
    )

    elements.append(
        Paragraph(
            "<b>CENTRAL LIBRARY</b>",
            styles["Heading2"]
        )
    )

    elements.append(Spacer(1,20))

    elements.append(
        Paragraph(
            f"<b>{title}</b>",
            styles["Heading1"]
        )
    )

    elements.append(
        Paragraph(
            f"Generated : {datetime.now().strftime('%d-%m-%Y %I:%M %p')}",
            styles["Normal"]
        )
    )

    elements.append(Spacer(1,20))

    table_data = [headers]

    table_data.extend(data)

    table = Table(table_data)

    table.setStyle(TableStyle([

        ("BACKGROUND",(0,0),(-1,0),colors.darkblue),

        ("TEXTCOLOR",(0,0),(-1,0),colors.white),

        ("GRID",(0,0),(-1,-1),1,colors.black),

        ("BACKGROUND",(0,1),(-1,-1),colors.beige),

        ("ALIGN",(0,0),(-1,-1),"CENTER"),

        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),

        ("BOTTOMPADDING",(0,0),(-1,0),12)

    ]))

    elements.append(table)

    elements.append(Spacer(1,30))

    elements.append(
        Paragraph(
            "Library Management System Version 1.0",
            styles["Normal"]
        )
    )

    elements.append(
        Paragraph(
            "Developed by Zidane Shaikh",
            styles["Normal"]
        )
    )

    doc.build(elements)

    buffer.seek(0)

    return buffer

def log_activity(action):
    """Record an admin action in the activity_logs table."""

    if "admin" in session:
        cursor.execute(
            """
            INSERT INTO activity_logs (username, role, action)
            VALUES (%s, %s, %s)
            """,
            (session["admin"], session["role"], action),
        )
        db.commit()


def get_library_date():
    """Return the current library date used for due-date/fine calculations."""

    cursor.execute("SELECT library_date FROM system_settings WHERE id=1")
    return cursor.fetchone()[0]


def get_student_notifications(student_id):
    """
    Return due-soon / overdue notifications for a student's currently
    borrowed books, based on the library's (possibly simulated) date.
    """

    today = get_library_date()
    warning_cutoff = today + timedelta(days=DUE_SOON_WINDOW_DAYS)

    cursor.execute(
        """
        SELECT b.title, bh.due_date
        FROM borrow_history bh
        JOIN books b ON bh.book_id = b.id
        WHERE bh.member_id=%s
        AND bh.status='Borrowed'
        AND bh.due_date <= %s
        ORDER BY bh.due_date ASC
        """,
        (student_id, warning_cutoff),
    )

    notifications = []

    for title, due_date in cursor.fetchall():
        if due_date < today:
            notifications.append({
                "title": title,
                "due_date": due_date,
                "type": "overdue",
                "days": (today - due_date).days,
            })
        else:
            notifications.append({
                "title": title,
                "due_date": due_date,
                "type": "due_soon",
                "days": (due_date - today).days,
            })

    return notifications


def ensure_notification_tracking_column():
    """
    Adds a 'last_notified_date' column to borrow_history if it doesn't
    already exist. Used to avoid emailing a student more than once a day
    about the same borrowed book. Safe to call repeatedly.
    """

    try:
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
            AND table_name = 'borrow_history'
            AND column_name = 'last_notified_date'
        """)
        exists = cursor.fetchone()[0]

        if not exists:
            cursor.execute("""
                ALTER TABLE borrow_history
                ADD COLUMN last_notified_date DATE NULL
            """)
            db.commit()
    except Exception as e:
        # Don't block app startup if this fails for any reason (e.g.
        # restricted DB permissions) - email reminders will just resend
        # more often than ideal until it's added.
        print(f"[warning] Could not verify/add last_notified_date column: {e}")


def send_email(to_email, to_name, subject, html_body):
    """
    Send a single HTML email via SMTP. Returns True on success, False if
    email isn't configured or sending failed (never raises, so callers
    can fire-and-forget this without risking a page-load crash).
    """

    if not EMAIL_NOTIFICATIONS_ENABLED or not to_email:
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg["To"] = to_email

        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USERNAME and SMTP_PASSWORD:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, [to_email], msg.as_string())

        return True

    except Exception as e:
        print(f"[warning] Failed to send email to {to_email}: {e}")
        return False


def build_due_date_email(student_name, book_title, notif_type, due_date, days):
    """Build the subject + HTML body for a due-date reminder email."""

    if notif_type == "overdue":
        subject = f"Overdue: '{book_title}' is now {days} day{'s' if days != 1 else ''} overdue"
        headline = "This book is overdue"
        message = (
            f"'<strong>{book_title}</strong>' was due on <strong>{due_date}</strong> "
            f"and is now <strong>{days} day{'s' if days != 1 else ''} overdue</strong>. "
            f"Fines accrue for each day it remains unreturned — please return it to "
            f"the library as soon as possible."
        )
        color = "#E5484D"
    elif days == 0:
        subject = f"Due today: '{book_title}'"
        headline = "This book is due today"
        message = (
            f"'<strong>{book_title}</strong>' is due back at the library "
            f"<strong>today ({due_date})</strong>. Please return or renew it to avoid a fine."
        )
        color = "#F0A202"
    else:
        subject = f"Reminder: '{book_title}' is due in {days} day{'s' if days != 1 else ''}"
        headline = "This book is due soon"
        message = (
            f"'<strong>{book_title}</strong>' is due back at the library in "
            f"<strong>{days} day{'s' if days != 1 else ''}</strong>, on <strong>{due_date}</strong>. "
            f"Please return or renew it before then to avoid a fine."
        )
        color = "#F0A202"

    html_body = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;">
        <div style="background:#202868;padding:20px 24px;border-radius:8px 8px 0 0;">
            <span style="color:#FFD873;font-size:12px;letter-spacing:.08em;text-transform:uppercase;font-weight:bold;">
                Central Library
            </span>
            <h2 style="color:#ffffff;margin:8px 0 0;font-size:20px;">{headline}</h2>
        </div>
        <div style="border:1px solid #DCDEEE;border-top:none;border-radius:0 0 8px 8px;padding:24px;">
            <p style="font-size:15px;color:#1B1F3B;margin:0 0 16px;">Hi {student_name},</p>
            <p style="font-size:15px;color:#1B1F3B;line-height:1.6;margin:0 0 16px;">
                {message}
            </p>
            <div style="border-left:4px solid {color};background:#F6F6FB;padding:12px 16px;border-radius:4px;">
                <strong style="color:{color};">{book_title}</strong><br>
                <span style="color:#61637E;font-size:14px;">Due date: {due_date}</span>
            </div>
            <p style="font-size:13px;color:#61637E;margin:24px 0 0;">
                This is an automated message from the Central Library Management System.
                Please do not reply to this email.
            </p>
        </div>
    </div>
    """

    return subject, html_body


def send_due_date_reminder_emails(member_id=None):
    """
    Emails students about books that are due soon or overdue, at most once
    per day per borrow record (tracked via last_notified_date). If
    member_id is given, only that student's books are checked - otherwise
    every currently-borrowed book in the system is checked.

    Returns the number of emails successfully sent.
    """

    if not EMAIL_NOTIFICATIONS_ENABLED:
        return 0

    today = get_library_date()
    warning_cutoff = today + timedelta(days=DUE_SOON_WINDOW_DAYS)

    query = """
        SELECT bh.id, b.title, bh.due_date, m.full_name, m.email
        FROM borrow_history bh
        JOIN books b ON bh.book_id = b.id
        JOIN members m ON bh.member_id = m.id
        WHERE bh.status = 'Borrowed'
        AND bh.due_date <= %s
        AND (bh.last_notified_date IS NULL OR bh.last_notified_date < %s)
    """
    params = [warning_cutoff, today]

    if member_id is not None:
        query += " AND bh.member_id = %s"
        params.append(member_id)

    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()

    sent_count = 0

    for record_id, title, due_date, student_name, student_email in rows:
        if due_date < today:
            notif_type, days = "overdue", (today - due_date).days
        else:
            notif_type, days = "due_soon", (due_date - today).days

        subject, html_body = build_due_date_email(
            student_name, title, notif_type, due_date, days
        )

        if send_email(student_email, student_name, subject, html_body):
            sent_count += 1
            cursor.execute(
                "UPDATE borrow_history SET last_notified_date=%s WHERE id=%s",
                (today, record_id),
            )
            db.commit()

    return sent_count


@app.context_processor
def inject_student_notifications():
    """
    Makes due-soon / overdue notifications available to every template
    (used by the student navbar's notification bell) without every route
    needing to fetch and pass it manually.
    """

    if session.get("student_id"):
        try:
            notifications = get_student_notifications(session["student_id"])
        except Exception:
            notifications = []

        overdue_count = sum(1 for n in notifications if n["type"] == "overdue")

        return dict(
            student_notifications=notifications,
            student_notif_count=len(notifications),
            student_overdue_count=overdue_count,
        )

    return dict(student_notifications=[], student_notif_count=0, student_overdue_count=0)


# Ensure the tracking column used for email reminders exists. Runs once
# when the app module loads (works the same under `python app.py` and
# under a production WSGI server).
ensure_notification_tracking_column()


# =========================================================
# Auth Routes
# =========================================================
@app.route("/")
def landing():

    return render_template("landing.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        cursor.execute("SELECT * FROM admins WHERE username=%s", (username,))
        admin = cursor.fetchone()

        if admin:
            stored_password = admin[3]
            password_ok = False

            # Hashed passwords (current standard)
            if stored_password.startswith("scrypt:") or stored_password.startswith("pbkdf2:"):
                password_ok = check_password_hash(stored_password, password)
            else:
                # Temporary support for legacy plain-text passwords.
                # NOTE: this path should be removed once all accounts are
                # migrated to hashed passwords - kept here only for
                # backward compatibility with existing data.
                password_ok = stored_password == password

            if password_ok:
                session["admin"] = admin[2]
                session["role"] = admin[4]
                flash("Login Successful!", "success")
                return redirect("/dashboard")

        flash("Invalid Username or Password!", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully!", "success")
    return redirect("/login")

# =========================================================
# Student Authentication
# =========================================================

@app.route("/student_login", methods=["GET", "POST"])
def student_login():

    if request.method == "POST":

        username = request.form["username"].strip()
        password = request.form["password"]

        cursor.execute("""
            SELECT
                id,
                full_name,
                username,
                password
            FROM members
            WHERE username = %s
        """, (username,))

        student = cursor.fetchone()

        if student:

            student_id = student[0]
            student_name = student[1]
            hashed_password = student[3]

            if check_password_hash(hashed_password, password):

                session["student_id"] = student_id
                session["student_name"] = student_name
                session["student_username"] = username

                flash(f"Welcome {student_name}!", "success")

                return redirect("/student_dashboard")

        flash("Invalid Username or Password!", "danger")

    return render_template("student_login.html")


@app.route("/student_logout")
@student_login_required
def student_logout():

    session.pop("student_id", None)
    session.pop("student_name", None)
    session.pop("student_username", None)

    flash("Logged out successfully!", "success")

    return redirect("/student_login")

@app.route("/student_dashboard")
@student_login_required
def student_dashboard():

    student_id = session["student_id"]

    # Student details
    cursor.execute("""
        SELECT full_name, email, phone
        FROM members
        WHERE id=%s
    """, (student_id,))

    student = cursor.fetchone()

    # Currently borrowed books
    cursor.execute("""
        SELECT COUNT(*)
        FROM borrow_history bh
        JOIN books b ON bh.book_id = b.id
        WHERE bh.member_id=%s
        AND bh.status='Borrowed'
    """, (student_id,))

    borrowed_books = cursor.fetchone()[0]

    # Due-soon / overdue notifications (uses the library's simulated date,
    # so this stays in sync with the admin's Date Simulator)
    notifications = get_student_notifications(student_id)
    due_soon = sum(1 for n in notifications if n["type"] == "due_soon")
    overdue_count = sum(1 for n in notifications if n["type"] == "overdue")

    # Best-effort email reminder for any due-soon/overdue books. Throttled
    # to once per day per book via last_notified_date, and never allowed
    # to break the page if email isn't configured or sending fails.
    try:
        send_due_date_reminder_emails(member_id=student_id)
    except Exception as e:
        print(f"[warning] Due-date email reminder failed: {e}")

    # Total fine
    cursor.execute("""
        SELECT IFNULL(SUM(fine),0)
        FROM borrow_history
        WHERE member_id=%s
    """, (student_id,))

    total_fine = cursor.fetchone()[0]

    # Recent borrowed books
    cursor.execute("""
        SELECT
            books.title,
            borrow_history.borrow_date,
            borrow_history.due_date,
            borrow_history.status
        FROM borrow_history
        JOIN books
            ON borrow_history.book_id = books.id
        WHERE borrow_history.member_id=%s
        ORDER BY borrow_history.borrow_date DESC
        LIMIT 5
    """, (student_id,))

    recent_books = cursor.fetchall()

    return render_template(
        "student_dashboard.html",
        student=student,
        borrowed_books=borrowed_books,
        due_soon=due_soon,
        overdue_count=overdue_count,
        total_fine=total_fine,
        recent_books=recent_books,
        notifications=notifications,
        today=get_library_date(),
    )

@app.route("/student_profile")
@student_login_required
def student_profile():

    student_id = session["student_id"]

    cursor.execute("""
        SELECT
            full_name,
            email,
            phone,
            username
        FROM members
        WHERE id=%s
    """, (student_id,))

    student = cursor.fetchone()

    return render_template(
        "student_profile.html",
        student=student
    )

@app.route("/student_change_password", methods=["GET", "POST"])
@student_login_required
def student_change_password():

    student_id = session["student_id"]

    if request.method == "POST":

        current_password = request.form["current_password"]
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        if new_password != confirm_password:
            flash("New passwords do not match!", "danger")
            return redirect("/student_change_password")

        cursor.execute("""
            SELECT password
            FROM members
            WHERE id=%s
        """, (student_id,))

        stored_password = cursor.fetchone()[0]

        if not check_password_hash(stored_password, current_password):
            flash("Current password is incorrect!", "danger")
            return redirect("/student_change_password")

        new_hash = generate_password_hash(new_password)

        cursor.execute("""
            UPDATE members
            SET password=%s
            WHERE id=%s
        """, (
            new_hash,
            student_id
        ))

        db.commit()

        flash("Password updated successfully!", "success")

        return redirect("/student_profile")

    return render_template("student_change_password.html")

@app.route("/student_books")
@student_login_required
def student_books():

    search = request.args.get("search", "")

    if search:

        cursor.execute("""
            SELECT
                title,
                author,
                category,
                quantity
            FROM books
            WHERE
                title LIKE %s
                OR author LIKE %s
                OR category LIKE %s
            ORDER BY title
        """, (
            f"%{search}%",
            f"%{search}%",
            f"%{search}%"
        ))

    else:

        cursor.execute("""
            SELECT
                title,
                author,
                category,
                quantity
            FROM books
            ORDER BY title
        """)

    books = cursor.fetchall()

    return render_template(
        "student_books.html",
        books=books,
        search=search
    )


# =========================================================
# Dashboard
# =========================================================

@app.route("/dashboard")
@login_required
def home():

    library_date = get_library_date()

    # -----------------------------
    # Search / List Books
    # -----------------------------
    search = request.args.get("search")

    if search:
        value = f"%{search}%"

        cursor.execute(
            """
            SELECT *
            FROM books
            WHERE title LIKE %s
               OR author LIKE %s
               OR category LIKE %s
            """,
            (value, value, value),
        )

    else:

        cursor.execute("SELECT * FROM books")

    books = cursor.fetchall()

    # -----------------------------
    # Dashboard Statistics
    # -----------------------------

    cursor.execute("SELECT COUNT(*) FROM books")
    total_books = cursor.fetchone()[0]

    cursor.execute("SELECT IFNULL(SUM(quantity),0) FROM books")
    total_quantity = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT category) FROM books")
    total_categories = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM members")
    total_members = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM borrow_history bh
        JOIN books b ON bh.book_id = b.id
        JOIN members m ON bh.member_id = m.id
        WHERE bh.status='Borrowed'
        """
    )
    borrowed_books = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM borrow_history bh
        JOIN books b ON bh.book_id = b.id
        JOIN members m ON bh.member_id = m.id
        WHERE bh.status='Borrowed'
          AND bh.due_date < %s
        """,
        (library_date,),
    )

    overdue_books = cursor.fetchone()[0]

    # -----------------------------
    # Outstanding Fine
    # -----------------------------

    cursor.execute(
        """
        SELECT IFNULL(SUM(fine),0)
        FROM borrow_history
        WHERE fine_paid='No'
        """
    )

    outstanding_fine = cursor.fetchone()[0]

    # -----------------------------
    # Returned Books
    # -----------------------------

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM borrow_history
        WHERE status='Returned'
        """
    )

    returned_books = cursor.fetchone()[0]

    # -----------------------------
    # Books by Category
    # -----------------------------

    cursor.execute(
        """
        SELECT category, COUNT(*)
        FROM books
        GROUP BY category
        ORDER BY category
        """
    )

    category_data = cursor.fetchall()

    # -----------------------------
    # Borrow Status Breakdown
    # -----------------------------

    cursor.execute(
        """
        SELECT status, COUNT(*)
        FROM borrow_history
        GROUP BY status
        """
    )

    borrow_stats = cursor.fetchall()

    # -----------------------------
    # Top Borrowed Books
    # -----------------------------

    cursor.execute(
        """
        SELECT books.title,
               COUNT(*) AS total

        FROM borrow_history

        JOIN books
            ON borrow_history.book_id = books.id

        GROUP BY books.id, books.title

        ORDER BY total DESC

        LIMIT 5
        """
    )

    top_books = cursor.fetchall()

    # -----------------------------
    # Recent Activities
    # -----------------------------

    cursor.execute(
        """
        SELECT action, log_time
        FROM activity_logs
        ORDER BY log_time DESC
        LIMIT 5
        """
    )

    recent_activities = cursor.fetchall()

    return render_template(
        "index.html",
        books=books,
        total_books=total_books,
        total_quantity=total_quantity,
        total_categories=total_categories,
        total_members=total_members,
        borrowed_books=borrowed_books,
        overdue_books=overdue_books,
        outstanding_fine=outstanding_fine,
        returned_books=returned_books,
        library_date=library_date,
        recent_activities=recent_activities,
        category_data=category_data,
        borrow_stats=borrow_stats,
        top_books=top_books,
    )

# =========================================================
# Book Routes
# =========================================================

@app.route("/add")
@login_required
def add():
    return render_template("add_book.html")


@app.route("/save", methods=["POST"])
@login_required
def save():
    title = request.form["title"]
    author = request.form["author"]
    category = request.form["category"]
    quantity = request.form["quantity"]

    cursor.execute(
        """
        INSERT INTO books (title, author, category, quantity)
        VALUES (%s, %s, %s, %s)
        """,
        (title, author, category, quantity),
    )
    db.commit()

    log_activity(f"Added Book: {title}")
    flash("Book added successfully!", "success")
    return redirect("/dashboard")


@app.route("/edit/<int:id>")
@login_required
def edit_book(id):
    cursor.execute("SELECT * FROM books WHERE id=%s", (id,))
    book = cursor.fetchone()
    return render_template("edit_book.html", book=book)


@app.route("/update/<int:id>", methods=["POST"])
@login_required
def update_book(id):
    title = request.form["title"]
    author = request.form["author"]
    category = request.form["category"]
    quantity = request.form["quantity"]

    cursor.execute(
        """
        UPDATE books
        SET title=%s, author=%s, category=%s, quantity=%s
        WHERE id=%s
        """,
        (title, author, category, quantity, id),
    )
    db.commit()

    log_activity(f"Edited Book: {title}")
    flash("Book updated successfully!", "warning")
    return redirect("/dashboard")


@app.route("/delete/<int:id>")
@login_required
def delete_book(id):
    cursor.execute(
        "SELECT COUNT(*) FROM borrow_history WHERE book_id=%s AND status='Borrowed'",
        (id,),
    )
    active_borrows = cursor.fetchone()[0]

    if active_borrows > 0:
        flash(
            "This book can't be deleted while a copy is still borrowed - "
            "please wait until it's returned first.",
            "danger",
        )
        return redirect("/dashboard")

    cursor.execute("DELETE FROM books WHERE id=%s", (id,))
    db.commit()

    log_activity(f"Deleted Book: {id}")
    flash("Book deleted successfully!", "danger")
    return redirect("/dashboard")


# =========================================================
# Borrow / Return Routes
# =========================================================

@app.route("/borrow/<int:id>")
@login_required
def borrow(id):
    cursor.execute("SELECT * FROM books WHERE id=%s", (id,))
    book = cursor.fetchone()

    cursor.execute("SELECT * FROM members")
    members = cursor.fetchall()

    today = get_library_date()

    return render_template("borrow_book.html", book=book, members=members, today=today)


@app.route("/borrow_book/<int:id>", methods=["POST"])
@login_required
def borrow_book(id):
    member_id = request.form["member_id"]

    cursor.execute("SELECT title, quantity FROM books WHERE id=%s", (id,))
    book = cursor.fetchone()

    if not book:
        flash("Book not found!", "danger")
        return redirect("/dashboard")

    book_title, quantity = book

    if quantity <= 0:
        flash("Book is currently unavailable!", "danger")
        return redirect("/dashboard")

    today = get_library_date()

    # Borrow date can be manually entered by the admin (e.g. to backdate an
    # already-issued book). Falls back to today's library date if left
    # blank or if the value can't be parsed.
    borrow_date_raw = request.form.get("borrow_date", "").strip()

    if borrow_date_raw:
        try:
            borrow_date = datetime.strptime(borrow_date_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid borrow date format. Using today's date instead.", "warning")
            borrow_date = today
    else:
        borrow_date = today

    if borrow_date > today:
        flash("Borrow date cannot be in the future. Using today's date instead.", "warning")
        borrow_date = today

    cursor.execute("UPDATE books SET quantity = quantity - 1 WHERE id=%s", (id,))

    due_date = borrow_date + timedelta(days=DEFAULT_LOAN_DAYS)

    cursor.execute(
        """
        INSERT INTO borrow_history
        (book_id, member_id, borrow_date, due_date, status)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (id, member_id, borrow_date, due_date, "Borrowed"),
    )
    db.commit()

    log_activity(f"Borrowed Book: {book_title}")
    flash("Book borrowed successfully!", "success")
    return redirect("/dashboard")


@app.route("/return_book/<int:id>")
@login_required
def return_book(id):
    cursor.execute(
        """
        SELECT bh.id, bh.book_id, b.title, m.full_name, bh.borrow_date, bh.due_date
        FROM borrow_history bh
        JOIN books b ON bh.book_id = b.id
        JOIN members m ON bh.member_id = m.id
        WHERE bh.id=%s
        """,
        (id,),
    )
    record = cursor.fetchone()

    if not record:
        flash("Borrow record not found!", "danger")
        return redirect("/borrow_history")

    today = get_library_date()

    overdue_days = 0
    fine = 0

    if record[5] and today > record[5]:
        overdue_days = (today - record[5]).days
        fine = overdue_days * 10

    return render_template(
        "return_book.html",
        record=record,
        today=today,
        overdue_days=overdue_days,
        fine=fine,
    )


@app.route("/confirm_return/<int:id>", methods=["POST"])
@login_required
def confirm_return(id):
    cursor.execute(
        "SELECT book_id, due_date FROM borrow_history WHERE id=%s", (id,)
    )
    record = cursor.fetchone()

    if not record:
        flash("Borrow record not found!", "danger")
        return redirect("/borrow_history")

    book_id, due_date = record
    today = get_library_date()

    fine = 0
    if due_date and today > due_date:
        overdue_days = (today - due_date).days
        fine = overdue_days * 10

    cursor.execute("UPDATE books SET quantity = quantity + 1 WHERE id=%s", (book_id,))

    cursor.execute(
    """
    UPDATE borrow_history
    SET
        return_date=%s,
        status='Returned',
        fine=%s,
        fine_paid=%s
    WHERE id=%s
    """,
    (
        today,
        fine,
        "No" if fine > 0 else "Yes",
        id,
    ),
)
    db.commit()

    flash(f"Book returned successfully! Fine Collected: ₹{fine}", "success")
    return redirect("/borrow_history")

@app.route("/receive_payment/<int:id>")
@login_required
def receive_payment(id):

    cursor.execute(
        """
        SELECT b.title, m.full_name, bh.fine
        FROM borrow_history bh
        JOIN books b ON bh.book_id = b.id
        JOIN members m ON bh.member_id = m.id
        WHERE bh.id=%s
        """,
        (id,),
    )
    record = cursor.fetchone()

    cursor.execute(
        """
        UPDATE borrow_history
        SET fine_paid='Yes'
        WHERE id=%s
        """,
        (id,),
    )

    db.commit()

    if record:
        book_title, member_name, fine_amount = record
        log_activity(
            f"Fine Payment Received: {member_name} - '{book_title}' (Rs.{fine_amount})"
        )
    else:
        log_activity(f"Fine Payment Received (Borrow ID: {id})")

    flash("Fine payment received successfully!", "success")

    return redirect("/borrow_history")


# =========================================================
# Member Routes
# =========================================================

@app.route("/members")
@login_required
def members():
    cursor.execute("SELECT * FROM members")
    members = cursor.fetchall()
    return render_template("members.html", members=members)


@app.route("/add_member")
@login_required
def add_member():
    return render_template("add_member.html")


@app.route("/save_member", methods=["POST"])
@login_required
def save_member():

    full_name = request.form["name"]
    email = request.form["email"]
    phone = request.form["phone"]
    username = request.form["username"]
    password = request.form["password"]

    # Check if username already exists
    cursor.execute(
        "SELECT id FROM members WHERE username=%s",
        (username,)
    )

    if cursor.fetchone():

        flash("Username already exists!", "danger")
        return redirect("/add_member")

    hashed_password = generate_password_hash(password)

    cursor.execute("""
        INSERT INTO members
        (full_name, email, phone, username, password)
        VALUES (%s,%s,%s,%s,%s)
    """, (
        full_name,
        email,
        phone,
        username,
        hashed_password
    ))

    db.commit()

    log_activity(f"Added Member: {full_name}")

    flash("Member added successfully!", "success")

    return redirect("/members")

@app.route("/edit_member/<int:id>")
@login_required
def edit_member(id):

    cursor.execute(
        "SELECT * FROM members WHERE id=%s",
        (id,)
    )

    member = cursor.fetchone()

    if not member:
        flash("Member not found!", "danger")
        return redirect("/members")

    return render_template(
        "edit_member.html",
        member=member
    )


@app.route("/update_member/<int:id>", methods=["POST"])
@login_required
def update_member(id):

    full_name = request.form["name"]
    email = request.form["email"]
    phone = request.form["phone"]
    username = request.form["username"]

    cursor.execute(
        """
        SELECT id
        FROM members
        WHERE username=%s
        AND id!=%s
        """,
        (username, id)
    )

    if cursor.fetchone():

        flash("Username already exists!", "danger")
        return redirect(f"/edit_member/{id}")

    cursor.execute(
        """
        UPDATE members
        SET
            full_name=%s,
            email=%s,
            phone=%s,
            username=%s
        WHERE id=%s
        """,
        (
            full_name,
            email,
            phone,
            username,
            id
        )
    )

    db.commit()

    log_activity(f"Edited Member: {full_name}")

    flash("Member updated successfully!", "success")

    return redirect("/members")

@app.route("/delete_member/<int:id>")
@login_required
def delete_member(id):
    cursor.execute(
        "SELECT COUNT(*) FROM borrow_history WHERE member_id=%s AND status='Borrowed'",
        (id,),
    )
    active_borrows = cursor.fetchone()[0]

    if active_borrows > 0:
        flash(
            "This member can't be deleted while they still have a book "
            "borrowed - please have them return it first.",
            "danger",
        )
        return redirect("/members")

    cursor.execute("DELETE FROM members WHERE id=%s", (id,))
    db.commit()

    log_activity(f"Deleted Member: {id}")
    flash("Member deleted successfully!", "danger")
    return redirect("/members")

@app.route("/reset_member_password/<int:id>", methods=["GET", "POST"])
@login_required
def reset_member_password(id):

    cursor.execute("""
        SELECT
            full_name
        FROM members
        WHERE id=%s
    """, (id,))

    member = cursor.fetchone()

    if not member:
        flash("Member not found!", "danger")
        return redirect("/members")

    if request.method == "POST":

        password = request.form["password"]
        confirm = request.form["confirm_password"]

        if password != confirm:

            flash("Passwords do not match!", "danger")
            return redirect(f"/reset_member_password/{id}")

        hashed = generate_password_hash(password)

        cursor.execute("""
            UPDATE members
            SET password=%s
            WHERE id=%s
        """, (
            hashed,
            id
        ))

        db.commit()

        log_activity(
            f"Reset Student Password: {member[0]}"
        )

        flash(
            "Student password updated successfully!",
            "success"
        )

        return redirect("/members")

    return render_template(
        "reset_member_password.html",
        member=member
    )


# =========================================================
# Borrow History
# =========================================================

@app.route("/borrow_history")
@login_required
def borrow_history():

    cursor.execute(
        """
        SELECT
            bh.id,
            b.title,
            m.full_name,
            bh.borrow_date,
            bh.due_date,
            bh.return_date,
            bh.status,
            bh.fine,
            bh.fine_paid
        FROM borrow_history bh
        JOIN books b
            ON bh.book_id = b.id
        JOIN members m
            ON bh.member_id = m.id
        ORDER BY bh.borrow_date DESC
        """
    )

    rows = cursor.fetchall()

    today = get_library_date()

    history = []

    for row in rows:

        row = list(row)

        overdue_days = 0

        fine = row[7]

        # Refresh fine for overdue borrowed books
        if row[6] == "Borrowed" and row[4] and today > row[4]:

            overdue_days = (today - row[4]).days

            fine = overdue_days * 10

            cursor.execute(
                """
                UPDATE borrow_history
                SET fine=%s
                WHERE id=%s
                """,
                (
                    fine,
                    row[0],
                ),
            )

        row[7] = fine

        # Append overdue days
        row.append(overdue_days)

        history.append(row)

    db.commit()

    return render_template(
        "borrow_history.html",
        history=history
    )


# =========================================================
# Library Date Controls
# =========================================================

@app.route("/update_library_date", methods=["POST"])
@login_required
def update_library_date():
    days = int(request.form["days"])

    cursor.execute(
        """
        UPDATE system_settings
        SET library_date = DATE_ADD(library_date, INTERVAL %s DAY)
        WHERE id=1
        """,
        (days,),
    )
    db.commit()

    flash(f"Library date advanced by {days} day(s).", "success")
    return redirect("/dashboard")


@app.route("/reset_library_date")
@login_required
def reset_library_date():
    cursor.execute("UPDATE system_settings SET library_date = CURDATE() WHERE id=1")
    db.commit()

    flash("Library date reset to today's date.", "warning")
    return redirect("/dashboard")


# =========================================================
# Admin Management
# =========================================================

@app.route("/admins")
@login_required
def admins():
    cursor.execute(
        """
        SELECT id, full_name, username, role, created_at
        FROM admins
        ORDER BY id
        """
    )
    admins = cursor.fetchall()
    return render_template("admins.html", admins=admins)


@app.route("/add_admin")
@role_required("Head Librarian")
def add_admin():
    return render_template("add_admin.html")


@app.route("/save_admin", methods=["POST"])
@role_required("Head Librarian")
def save_admin():
    full_name = request.form["full_name"]
    username = request.form["username"]
    password = request.form["password"]
    hashed_password = generate_password_hash(password)
    role = request.form["role"]

    cursor.execute("SELECT id FROM admins WHERE username=%s", (username,))
    if cursor.fetchone():
        flash("Username already exists!", "danger")
        return redirect("/add_admin")

    cursor.execute(
        """
        INSERT INTO admins (full_name, username, password, role)
        VALUES (%s, %s, %s, %s)
        """,
        (full_name, username, hashed_password, role),
    )
    db.commit()

    log_activity(f"Added Admin: {full_name}")
    flash("New admin created successfully!", "success")
    return redirect("/admins")


@app.route("/edit_admin/<int:id>")
@role_required("Head Librarian")
def edit_admin(id):
    cursor.execute("SELECT * FROM admins WHERE id=%s", (id,))
    admin = cursor.fetchone()
    return render_template("edit_admin.html", admin=admin)


@app.route("/update_admin/<int:id>", methods=["POST"])
@role_required("Head Librarian")
def update_admin(id):
    full_name = request.form["full_name"]
    username = request.form["username"]
    role = request.form["role"]

    cursor.execute(
        """
        UPDATE admins
        SET full_name=%s, username=%s, role=%s
        WHERE id=%s
        """,
        (full_name, username, role, id),
    )
    db.commit()

    log_activity(f"Edited Admin: {full_name}")
    flash("Admin updated successfully!", "success")
    return redirect("/admins")


@app.route("/delete_admin/<int:id>")
@role_required("Head Librarian")
def delete_admin(id):
    cursor.execute("SELECT username, role FROM admins WHERE id=%s", (id,))
    admin = cursor.fetchone()

    if not admin:
        flash("Admin not found!", "danger")
        return redirect("/admins")

    username, role = admin

    if username == session["admin"]:
        flash("You cannot delete your own account!", "danger")
        return redirect("/admins")

    if role == "Head Librarian":
        cursor.execute("SELECT COUNT(*) FROM admins WHERE role='Head Librarian'")
        total_heads = cursor.fetchone()[0]

        if total_heads <= 1:
            flash("At least one Head Librarian must remain!", "danger")
            return redirect("/admins")

    cursor.execute("DELETE FROM admins WHERE id=%s", (id,))
    db.commit()

    log_activity(f"Deleted Admin: {username}")
    flash("Admin deleted successfully!", "success")
    return redirect("/admins")


# =========================================================
# Activity Logs
# =========================================================

@app.route("/activity_logs")
@role_required("Head Librarian")
def activity_logs():
    search = request.args.get("search")

    if search:
        value = f"%{search}%"
        cursor.execute(
            """
            SELECT username, role, action, log_time
            FROM activity_logs
            WHERE username LIKE %s OR action LIKE %s
            ORDER BY log_time DESC
            """,
            (value, value),
        )
    else:
        cursor.execute(
            """
            SELECT username, role, action, log_time
            FROM activity_logs
            ORDER BY log_time DESC
            """
        )

    logs = cursor.fetchall()
    return render_template("activity_logs.html", logs=logs)


# =========================================================
# Reports
# =========================================================

@app.route("/reports")
@role_required("Head Librarian", "Librarian")
def reports():
    cursor.execute("SELECT COUNT(*) FROM books")
    total_books = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(quantity) FROM books")
    total_quantity = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM members")
    total_members = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*) FROM borrow_history bh
        JOIN books b ON bh.book_id = b.id
        JOIN members m ON bh.member_id = m.id
        WHERE bh.status='Borrowed'
        """
    )
    borrowed_books = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM borrow_history WHERE status='Returned'")
    returned_books = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(fine) FROM borrow_history")
    total_fines = cursor.fetchone()[0] or 0

    cursor.execute(
        """
        SELECT COUNT(*) FROM borrow_history bh
        JOIN books b ON bh.book_id = b.id
        JOIN members m ON bh.member_id = m.id
        WHERE bh.status='Borrowed' AND bh.due_date < %s
        """,
        (get_library_date(),),
    )
    overdue_books = cursor.fetchone()[0]

    return render_template(
        "reports.html",
        total_books=total_books,
        total_quantity=total_quantity,
        total_members=total_members,
        borrowed_books=borrowed_books,
        returned_books=returned_books,
        overdue_books=overdue_books,
        total_fines=total_fines,
        email_enabled=EMAIL_NOTIFICATIONS_ENABLED,
    )


@app.route("/send_due_reminders", methods=["POST"])
@role_required("Head Librarian", "Librarian")
def send_due_reminders():
    if not EMAIL_NOTIFICATIONS_ENABLED:
        flash(
            "Email isn't configured yet (set SMTP_HOST / SMTP_FROM_EMAIL "
            "and related environment variables) - no emails were sent.",
            "warning",
        )
        return redirect("/reports")

    try:
        sent_count = send_due_date_reminder_emails()
    except Exception as e:
        flash(f"Something went wrong while sending reminder emails: {e}", "danger")
        return redirect("/reports")

    log_activity(f"Sent {sent_count} due-date reminder email(s)")

    if sent_count:
        flash(f"Sent {sent_count} due-date reminder email(s) to students.", "success")
    else:
        flash("No students needed a reminder right now.", "info")

    return redirect("/reports")

@app.route("/export/books")
@login_required
def export_books():

    cursor.execute("""
        SELECT
            title,
            author,
            category,
            quantity
        FROM books
        ORDER BY title
    """)

    books = cursor.fetchall()

    pdf = create_pdf(
        "BOOK INVENTORY REPORT",
        ["Title", "Author", "Category", "Copies"],
        books,
    )

    return send_file(
        pdf,
        download_name=f"Books_Report_{datetime.now().strftime('%Y%m%d')}.pdf",
        as_attachment=True,
        mimetype="application/pdf",
    )

@app.route("/export/members")
@login_required
def export_members():

    cursor.execute("""
        SELECT
            id,
            full_name,
            email,
            phone
        FROM members
        ORDER BY full_name
    """)

    members = cursor.fetchall()

    pdf = create_pdf(
        "LIBRARY MEMBERS REPORT",
        ["ID", "Member Name", "Email", "Phone"],
        members,
    )

    return send_file(
        pdf,
        download_name=f"Members_Report_{datetime.now().strftime('%Y%m%d')}.pdf",
        as_attachment=True,
        mimetype="application/pdf",
    )

@app.route("/export/borrow")
@login_required
def export_borrow():

    cursor.execute("""
        SELECT
            b.title,
            m.full_name,
            bh.borrow_date,
            bh.due_date,
            bh.return_date,
            bh.status
        FROM borrow_history bh
        JOIN books b ON bh.book_id = b.id
        JOIN members m ON bh.member_id = m.id
        ORDER BY bh.borrow_date DESC
    """)

    history = cursor.fetchall()

    pdf = create_pdf(
        "BORROW HISTORY REPORT",
        ["Book", "Member", "Borrowed", "Due", "Returned", "Status"],
        history,
    )

    return send_file(
        pdf,
        download_name=f"Borrow_History_{datetime.now().strftime('%Y%m%d')}.pdf",
        as_attachment=True,
        mimetype="application/pdf",
    )

@app.route("/export/fines")
@login_required
def export_fines():

    cursor.execute("""
        SELECT
            b.title,
            m.full_name,
            bh.fine,
            bh.fine_paid
        FROM borrow_history bh
        JOIN books b ON bh.book_id = b.id
        JOIN members m ON bh.member_id = m.id
        WHERE bh.fine > 0
        ORDER BY bh.fine DESC
    """)

    fines = cursor.fetchall()

    pdf = create_pdf(
        "FINE COLLECTION REPORT",
        ["Book", "Member", "Fine", "Paid"],
        fines,
    )

    return send_file(
        pdf,
        download_name=f"Fine_Report_{datetime.now().strftime('%Y%m%d')}.pdf",
        as_attachment=True,
        mimetype="application/pdf",
    )

@app.route("/export/complete")
@login_required
def export_complete():

    cursor.execute("SELECT COUNT(*) FROM books")
    total_books = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM members")
    total_members = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM borrow_history WHERE status='Borrowed'")
    borrowed = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM borrow_history WHERE status='Returned'")
    returned = cursor.fetchone()[0]

    cursor.execute("SELECT IFNULL(SUM(fine),0) FROM borrow_history")
    fines = cursor.fetchone()[0]

    data = [
        ["Total Books", total_books],
        ["Total Members", total_members],
        ["Borrowed Books", borrowed],
        ["Returned Books", returned],
        ["Total Fine Collected", f"₹{fines}"],
    ]

    pdf = create_pdf(
        "COMPLETE LIBRARY SUMMARY",
        ["Description", "Value"],
        data,
    )

    return send_file(
        pdf,
        download_name=f"Library_Report_{datetime.now().strftime('%Y%m%d')}.pdf",
        as_attachment=True,
        mimetype="application/pdf",
    )

# =========================================================
# Error Handlers
# =========================================================

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template("500.html"), 500


# =========================================================
# Entry Point
# =========================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )