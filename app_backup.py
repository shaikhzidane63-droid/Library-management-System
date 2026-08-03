

from flask import Flask, render_template, request, redirect, flash, session
from datetime import date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector

app = Flask(__name__)
app.secret_key = "library_secret_key"


db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="Zndag8",
    database="library_management_system"
)

cursor = db.cursor()

# -------------------------
# Permission Helper
# -------------------------

def require_role(allowed_roles):

    if "admin" not in session:
        return redirect("/login")

    if session.get("role") not in allowed_roles:
        flash("Access Denied!", "danger")
        return redirect("/")

    return None
# -------------------------
# Activity Logger
# -------------------------

def log_activity(action):

    if "admin" in session:

        cursor.execute("""
            INSERT INTO activity_logs
            (username, role, action)
            VALUES(%s, %s, %s)
        """, (
            session["admin"],
            session["role"],
            action
        ))

        db.commit()

# -------------------------
# Login
# -------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        cursor.execute(
            "SELECT * FROM admins WHERE username=%s",
            (username,)
        )

        admin = cursor.fetchone()

        if admin:

            stored_password = admin[3]

            # Support hashed passwords
            if stored_password.startswith("scrypt:") or stored_password.startswith("pbkdf2:"):

                if check_password_hash(stored_password, password):

                    session["admin"] = admin[2]
                    session["role"] = admin[4]

                    flash("Login Successful!", "success")

                    return redirect("/")

            # Temporary support for old plain-text passwords
            else:

                if stored_password == password:

                    session["admin"] = admin[2]
                    session["role"] = admin[4]

                    flash("Login Successful!", "success")

                    return redirect("/")

        flash("Invalid Username or Password!", "danger")

    return render_template("login.html")


# -------------------------
# Logout
# -------------------------

@app.route("/logout")
def logout():

    session.clear()

    flash("Logged out successfully!", "success")

    return redirect("/login")

@app.route("/")
def home():

    if "admin" not in session:
        return redirect("/login")

    # ==========================
    # Library Date
    # ==========================

    cursor.execute(
        "SELECT library_date FROM system_settings WHERE id=1"
    )

    library_date = cursor.fetchone()[0]

    # ==========================
    # Search Books
    # ==========================

    search = request.args.get("search")

    if search:

        sql = """
        SELECT *
        FROM books
        WHERE title LIKE %s
        OR author LIKE %s
        OR category LIKE %s
        """

        value = "%" + search + "%"

        cursor.execute(
            sql,
            (value, value, value)
        )

    else:

        cursor.execute(
            "SELECT * FROM books"
        )

    books = cursor.fetchall()

    # ==========================
    # Dashboard Statistics
    # ==========================

    cursor.execute(
        "SELECT COUNT(*) FROM books"
    )

    total_books = cursor.fetchone()[0]

    cursor.execute("""
        SELECT IFNULL(SUM(quantity),0)
        FROM books
    """)

    total_quantity = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(DISTINCT category)
        FROM books
    """)

    total_categories = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM members
    """)

    total_members = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM borrow_history
        WHERE status='Borrowed'
    """)

    borrowed_books = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM borrow_history
        WHERE status='Borrowed'
        AND due_date < CURDATE()
    """)

    overdue_books = cursor.fetchone()[0]

    # ==========================
    # Recent Activities
    # ==========================

    cursor.execute("""
        SELECT
            action,
            created_at
        FROM activity_logs
        ORDER BY created_at DESC
        LIMIT 5
    """)

    recent_activities = cursor.fetchall()

    # ==========================
    # Books by Category
    # ==========================

    cursor.execute("""
        SELECT
            category,
            COUNT(*)
        FROM books
        GROUP BY category
        ORDER BY category
    """)

    category_data = cursor.fetchall()

    # ==========================
    # Borrow Status Statistics
    # ==========================

    cursor.execute("""
        SELECT
            status,
            COUNT(*)
        FROM borrow_history
        GROUP BY status
    """)

    borrow_stats = cursor.fetchall()

    # ==========================
    # Top Borrowed Books
    # ==========================

    cursor.execute("""
        SELECT
            books.title,
            COUNT(*) AS total
        FROM borrow_history
        JOIN books
            ON borrow_history.book_id = books.id
        GROUP BY books.title
        ORDER BY total DESC
        LIMIT 5
    """)

    top_books = cursor.fetchall()

    # ==========================
    # Load Dashboard
    # ==========================

    return render_template(

        "index.html",

        books=books,

        total_books=total_books,

        total_quantity=total_quantity,

        total_categories=total_categories,

        total_members=total_members,

        borrowed_books=borrowed_books,

        overdue_books=overdue_books,

        library_date=library_date,

        recent_activities=recent_activities,

        category_data=category_data,

        borrow_stats=borrow_stats,

        top_books=top_books

    )

# -------------------------
# Add Book
# -------------------------

@app.route("/add")
def add():

    return render_template("add_book.html")

@app.route("/save", methods=["POST"])
def save():

    title = request.form["title"]
    author = request.form["author"]
    category = request.form["category"]
    quantity = request.form["quantity"]

    sql = """
    INSERT INTO books(title, author, category, quantity)
    VALUES(%s,%s,%s,%s)
    """

    cursor.execute(sql, (title, author, category, quantity))

    db.commit()

    log_activity(f"Added Book: {title}")

    flash("Book added successfully!", "success")

    return redirect("/")

# -------------------------
# Edit Book
# -------------------------

@app.route("/edit/<int:id>")
def edit_book(id):

    cursor.execute("SELECT * FROM books WHERE id=%s", (id,))
    book = cursor.fetchone()

    return render_template("edit_book.html", book=book)


@app.route("/update/<int:id>", methods=["POST"])
def update_book(id):

    title = request.form["title"]
    author = request.form["author"]
    category = request.form["category"]
    quantity = request.form["quantity"]

    sql = """
    UPDATE books
    SET title=%s,
        author=%s,
        category=%s,
        quantity=%s
    WHERE id=%s
    """

    cursor.execute(sql, (title, author, category, quantity, id))

    db.commit()

    log_activity(f"Edited Book: {title}")

    flash("Book updated successfully!", "warning")

    return redirect("/")

# -------------------------
# Delete Book
# -------------------------

@app.route("/delete/<int:id>")
def delete_book(id):

    cursor.execute("DELETE FROM books WHERE id=%s", (id,))
    db.commit()

    log_activity(f"Deleted Book: {id}")

    flash("Book deleted successfully!", "danger")

    return redirect("/")

# -------------------------
# Borrow Book
# -------------------------
@app.route("/borrow/<int:id>")
def borrow(id):

    cursor.execute("SELECT * FROM books WHERE id=%s", (id,))
    book = cursor.fetchone()

    cursor.execute("SELECT * FROM members")
    members = cursor.fetchall()

    return render_template(
        "borrow_book.html",
        book=book,
        members=members
    )


@app.route("/borrow_book/<int:id>", methods=["POST"])
def borrow_book(id):

    member_id = request.form["member_id"]

    # Get current quantity and book title
    cursor.execute(
        "SELECT title, quantity FROM books WHERE id=%s",
        (id,)
    )

    book = cursor.fetchone()

    book_title = book[0]
    quantity = book[1]

    # Check availability
    if quantity <= 0:
        flash("Book is currently unavailable!", "danger")
        return redirect("/")

    # Reduce quantity
    cursor.execute(
        "UPDATE books SET quantity = quantity - 1 WHERE id=%s",
        (id,)
    )

    borrow_date = date.today()
    due_date = borrow_date + timedelta(days=14)

    # Save borrow record
    cursor.execute("""
        INSERT INTO borrow_history
        (book_id, member_id, borrow_date, due_date, status)
        VALUES(%s, %s, %s, %s, %s)
    """, (
        id,
        member_id,
        borrow_date,
        due_date,
        "Borrowed"
    ))

    db.commit()

    # Log activity
    log_activity(f"Borrowed Book: {book_title}")

    flash("Book borrowed successfully!", "success")

    return redirect("/")
# -------------------------
# Return Book (Preview)
# -------------------------

@app.route("/return_book/<int:id>")
def return_book(id):

    cursor.execute("""
        SELECT
            bh.id,
            bh.book_id,
            b.title,
            m.full_name,
            bh.borrow_date,
            bh.due_date
        FROM borrow_history bh
        JOIN books b
            ON bh.book_id = b.id
        JOIN members m
            ON bh.member_id = m.id
        WHERE bh.id=%s
    """, (id,))

    record = cursor.fetchone()

    # Current library date
    cursor.execute("SELECT library_date FROM system_settings WHERE id=1")
    today = cursor.fetchone()[0]

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
        fine=fine
    )

# -------------------------
# Confirm Return
# -------------------------

@app.route("/confirm_return/<int:id>", methods=["POST"])
def confirm_return(id):

    cursor.execute("""
        SELECT book_id, due_date
        FROM borrow_history
        WHERE id=%s
    """, (id,))

    record = cursor.fetchone()

    book_id = record[0]
    due_date = record[1]

    # Current library date
    cursor.execute("SELECT library_date FROM system_settings WHERE id=1")
    today = cursor.fetchone()[0]

    fine = 0

    if due_date and today > due_date:
        overdue_days = (today - due_date).days
        fine = overdue_days * 10

    cursor.execute("""
        UPDATE books
        SET quantity = quantity + 1
        WHERE id=%s
    """, (book_id,))

    cursor.execute("""
        UPDATE borrow_history
        SET
            return_date=%s,
            status='Returned',
            fine=%s
        WHERE id=%s
    """, (
        today,
        fine,
        id
    ))

    db.commit()

    flash(f"Book returned successfully! Fine Collected: ₹{fine}", "success")

    return redirect("/borrow_history")


# -------------------------
# Members
# -------------------------

@app.route("/members")
def members():

    cursor.execute("SELECT * FROM members")

    members = cursor.fetchall()

    return render_template(
        "members.html",
        members=members
    )



# -------------------------
# Add Member
# -------------------------

@app.route("/add_member")
def add_member():

    return render_template("add_member.html")


@app.route("/save_member", methods=["POST"])
def save_member():

    full_name = request.form["name"]
    email = request.form["email"]
    phone = request.form["phone"]

    sql = """
    INSERT INTO members(full_name, email, phone)
    VALUES(%s, %s, %s)
    """

    cursor.execute(sql, (full_name, email, phone))

    db.commit()

    log_activity(f"Added Member: {full_name}")

    flash("Member added successfully!", "success")

    return redirect("/members")

# -------------------------
# Edit Member
# -------------------------

@app.route("/edit_member/<int:id>")
def edit_member(id):

    cursor.execute("SELECT * FROM members WHERE id=%s", (id,))
    member = cursor.fetchone()

    return render_template("edit_member.html", member=member)


@app.route("/update_member/<int:id>", methods=["POST"])
def update_member(id):

    full_name = request.form["name"]
    email = request.form["email"]
    phone = request.form["phone"]

    sql = """
    UPDATE members
    SET full_name=%s,
        email=%s,
        phone=%s
    WHERE id=%s
    """

    cursor.execute(sql, (full_name, email, phone, id))

    db.commit()

    log_activity(f"Edited Member: {full_name}")

    flash("Member updated successfully!", "warning")

    return redirect("/members")


# -------------------------
# Delete Member
# -------------------------

@app.route("/delete_member/<int:id>")
def delete_member(id):

    cursor.execute("DELETE FROM members WHERE id=%s", (id,))

    db.commit()

    log_activity(f"Deleted Member: {id}")

    flash("Member deleted successfully!", "danger")

    return redirect("/members")
# -------------------------
# Borrow History
# -------------------------
@app.route("/borrow_history")
def borrow_history():

    cursor.execute("""
        SELECT
            bh.id,
            b.title,
            m.full_name,
            bh.borrow_date,
            bh.due_date,
            bh.return_date,
            bh.status,
            bh.fine
                          
        FROM borrow_history bh
        JOIN books b
            ON bh.book_id = b.id
        JOIN members m
            ON bh.member_id = m.id
        ORDER BY bh.borrow_date DESC
    """)

    rows = cursor.fetchall()

    history = []

    cursor.execute("SELECT library_date FROM system_settings WHERE id=1")
    today = cursor.fetchone()[0]

    for row in rows:

        row = list(row)

        overdue_days = 0
        fine = row[7]

        if row[6] == "Borrowed" and row[4]:

            if today > row[4]:
               overdue_days = (today - row[4]).days
               fine = overdue_days * 10
               fine = overdue_days * 10

            cursor.execute("""
                UPDATE borrow_history
                SET fine=%s
                WHERE id=%s
            """, (
                fine,
                row[0]
            ))
               
        row[7] = fine
        row.append(overdue_days)

        history.append(row)
        print(history)

    db.commit()


    return render_template(
        "borrow_history.html",
        history=history
    )

# -------------------------
# Update Library Date
# -------------------------

@app.route("/update_library_date", methods=["POST"])
def update_library_date():

    if "admin" not in session:
        return redirect("/login")

    days = int(request.form["days"])

    cursor.execute("""
        UPDATE system_settings
        SET library_date = DATE_ADD(library_date, INTERVAL %s DAY)
        WHERE id=1
    """, (days,))

    db.commit()

    flash(f"Library date advanced by {days} day(s).", "success")

    return redirect("/")


# -------------------------
# Reset Library Date
# -------------------------

@app.route("/reset_library_date")
def reset_library_date():

    if "admin" not in session:
        return redirect("/login")

    cursor.execute("""
        UPDATE system_settings
        SET library_date = CURDATE()
        WHERE id=1
    """)

    db.commit()

    flash("Library date reset to today's date.", "warning")

    return redirect("/")

# -------------------------
# Admin Management
# -------------------------

@app.route("/admins")
def admins():

    if "admin" not in session:
        return redirect("/login")

    cursor.execute("""
        SELECT
            id,
            full_name,
            username,
            role,
            created_at
        FROM admins
        ORDER BY id
    """)

    admins = cursor.fetchall()

    return render_template(
        "admins.html",
        admins=admins
    )

# -------------------------
# Add Admin
# -------------------------

@app.route("/add_admin")
def add_admin():

    access = require_role(["Head Librarian"])

    if access:
        return access

    return render_template("add_admin.html")

@app.route("/save_admin", methods=["POST"])
def save_admin():

    access = require_role(["Head Librarian"])

    if access:
        return access

    full_name = request.form["full_name"]
    username = request.form["username"]
    password = request.form["password"]
    hashed_password = generate_password_hash(password)
    role = request.form["role"]

    # Check if username already exists
    cursor.execute(
        "SELECT id FROM admins WHERE username=%s",
        (username,)
    )

    if cursor.fetchone():

        flash("Username already exists!", "danger")

        return redirect("/add_admin")

    cursor.execute("""
    INSERT INTO admins
    (full_name, username, password, role)
    VALUES(%s,%s,%s,%s)
""",(
    full_name,
    username,
    hashed_password,
    role
))

    db.commit()

    log_activity(f"Added Admin: {full_name}")

    flash("New admin created successfully!", "success")

    return redirect("/admins")

# -------------------------
# Edit Admin
# -------------------------

@app.route("/edit_admin/<int:id>")
def edit_admin(id):

    access = require_role(["Head Librarian"])

    if access:
        return access

    cursor.execute(
        "SELECT * FROM admins WHERE id=%s",
        (id,)
    )

    admin = cursor.fetchone()

    return render_template(
        "edit_admin.html",
        admin=admin
    )


@app.route("/update_admin/<int:id>", methods=["POST"])
def update_admin(id):

    access = require_role(["Head Librarian"])

    if access:
        return access

    full_name = request.form["full_name"]
    username = request.form["username"]
    role = request.form["role"]

    cursor.execute("""
        UPDATE admins
        SET
            full_name=%s,
            username=%s,
            role=%s
        WHERE id=%s
    """, (
        full_name,
        username,
        role,
        id
    ))

    db.commit()

    log_activity(f"Edited Admin: {full_name}")

    flash(
        "Admin updated successfully!",
        "success"
    )

    return redirect("/admins")

# -------------------------
# Delete Admin
# -------------------------

@app.route("/delete_admin/<int:id>")
def delete_admin(id):

    access = require_role(["Head Librarian"])

    if access:
        return access

    # Get selected admin
    cursor.execute("""
        SELECT username, role
        FROM admins
        WHERE id=%s
    """, (id,))

    admin = cursor.fetchone()

    if not admin:

        flash("Admin not found!", "danger")

        return redirect("/admins")

    username = admin[0]
    role = admin[1]

    # Prevent deleting yourself
    if username == session["admin"]:

        flash("You cannot delete your own account!", "danger")

        return redirect("/admins")

    # Prevent deleting the last Head Librarian
    if role == "Head Librarian":

        cursor.execute("""
            SELECT COUNT(*)
            FROM admins
            WHERE role='Head Librarian'
        """)

        total_heads = cursor.fetchone()[0]

        if total_heads <= 1:

            flash(
                "At least one Head Librarian must remain!",
                "danger"
            )

            return redirect("/admins")

    # Delete admin
    cursor.execute(
        "DELETE FROM admins WHERE id=%s",
        (id,)
    )

    db.commit()

    log_activity(f"Deleted Admin: {username}")

    flash(
        "Admin deleted successfully!",
        "success"
    )

    return redirect("/admins")


from flask import Flask, render_template, request, redirect, flash, session
from datetime import date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector

app = Flask(__name__)
app.secret_key = "library_secret_key"


db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="Zndag8",
    database="library_management_system"
)

cursor = db.cursor()

# -------------------------
# Permission Helper
# -------------------------

def require_role(allowed_roles):

    if "admin" not in session:
        return redirect("/login")

    if session.get("role") not in allowed_roles:
        flash("Access Denied!", "danger")
        return redirect("/")

    return None
# -------------------------
# Activity Logger
# -------------------------

def log_activity(action):

    if "admin" in session:

        cursor.execute("""
            INSERT INTO activity_logs
            (username, role, action)
            VALUES(%s, %s, %s)
        """, (
            session["admin"],
            session["role"],
            action
        ))

        db.commit()

# -------------------------
# Login
# -------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        cursor.execute(
            "SELECT * FROM admins WHERE username=%s",
            (username,)
        )

        admin = cursor.fetchone()

        if admin:

            stored_password = admin[3]

            # Support hashed passwords
            if stored_password.startswith("scrypt:") or stored_password.startswith("pbkdf2:"):

                if check_password_hash(stored_password, password):

                    session["admin"] = admin[2]
                    session["role"] = admin[4]

                    flash("Login Successful!", "success")

                    return redirect("/")

            # Temporary support for old plain-text passwords
            else:

                if stored_password == password:

                    session["admin"] = admin[2]
                    session["role"] = admin[4]

                    flash("Login Successful!", "success")

                    return redirect("/")

        flash("Invalid Username or Password!", "danger")

    return render_template("login.html")


# -------------------------
# Logout
# -------------------------

@app.route("/logout")
def logout():

    session.clear()

    flash("Logged out successfully!", "success")

    return redirect("/login")

@app.route("/")
def home():

    if "admin" not in session:
        return redirect("/login")

    # ==========================
    # Library Date
    # ==========================

    cursor.execute("SELECT library_date FROM system_settings WHERE id=1")
    library_date = cursor.fetchone()[0]

    # ==========================
    # Search Books
    # ==========================

    search = request.args.get("search")

    if search:

        sql = """
        SELECT * FROM books
        WHERE title LIKE %s
        OR author LIKE %s
        OR category LIKE %s
        """

        value = "%" + search + "%"

        cursor.execute(sql, (value, value, value))

    else:

        cursor.execute("SELECT * FROM books")

    books = cursor.fetchall()

    # ==========================
    # Dashboard Statistics
    # ==========================

    cursor.execute("SELECT COUNT(*) FROM books")
    total_books = cursor.fetchone()[0]

    cursor.execute("SELECT IFNULL(SUM(quantity),0) FROM books")
    total_quantity = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT category) FROM books")
    total_categories = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM members")
    total_members = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM borrow_history
        WHERE status='Borrowed'
    """)
    borrowed_books = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM borrow_history
        WHERE status='Borrowed'
        AND due_date < CURDATE()
    """)
    overdue_books = cursor.fetchone()[0]

    # ==========================
    # Analytics Data
    # ==========================

    cursor.execute("""
        SELECT category, COUNT(*)
        FROM books
        GROUP BY category
    """)
    category_data = cursor.fetchall()

    cursor.execute("""
        SELECT status, COUNT(*)
        FROM borrow_history
        GROUP BY status
    """)
    borrow_stats = cursor.fetchall()

    cursor.execute("""
    SELECT books.title, COUNT(*) AS total
    FROM borrow_history
    JOIN books
        ON borrow_history.book_id = books.id
    GROUP BY books.id, books.title
    ORDER BY total DESC
    LIMIT 5
    """)
    top_books = cursor.fetchall()

    # ==========================
    # Recent Activities
    # ==========================
    cursor.execute("""
    SELECT action, log_time
    FROM activity_logs
    ORDER BY log_time DESC
    LIMIT 5
    """)
    recent_activities = cursor.fetchall()

    # ==========================
    # Load Dashboard
    # ==========================

    return render_template(

        "index.html",

        books=books,

        total_books=total_books,

        total_quantity=total_quantity,

        total_categories=total_categories,

        total_members=total_members,

        borrowed_books=borrowed_books,

        overdue_books=overdue_books,

        library_date=library_date,

        recent_activities=recent_activities,

        category_data=category_data,

        borrow_stats=borrow_stats,

        top_books=top_books

    )
# -------------------------
# Add Book
# -------------------------

@app.route("/add")
def add():

    return render_template("add_book.html")

@app.route("/save", methods=["POST"])
def save():

    title = request.form["title"]
    author = request.form["author"]
    category = request.form["category"]
    quantity = request.form["quantity"]

    sql = """
    INSERT INTO books(title, author, category, quantity)
    VALUES(%s,%s,%s,%s)
    """

    cursor.execute(sql, (title, author, category, quantity))

    db.commit()

    log_activity(f"Added Book: {title}")

    flash("Book added successfully!", "success")

    return redirect("/")

# -------------------------
# Edit Book
# -------------------------

@app.route("/edit/<int:id>")
def edit_book(id):

    cursor.execute("SELECT * FROM books WHERE id=%s", (id,))
    book = cursor.fetchone()

    return render_template("edit_book.html", book=book)


@app.route("/update/<int:id>", methods=["POST"])
def update_book(id):

    title = request.form["title"]
    author = request.form["author"]
    category = request.form["category"]
    quantity = request.form["quantity"]

    sql = """
    UPDATE books
    SET title=%s,
        author=%s,
        category=%s,
        quantity=%s
    WHERE id=%s
    """

    cursor.execute(sql, (title, author, category, quantity, id))

    db.commit()
    
    log_activity(f"Edited Book: {title}")

    flash("Book updated successfully!", "warning")

    return redirect("/")

# -------------------------
# Delete Book
# -------------------------

@app.route("/delete/<int:id>")
def delete_book(id):

    cursor.execute("DELETE FROM books WHERE id=%s", (id,))
    db.commit()

    log_activity(f"Deleted Book: {id}")

    flash("Book deleted successfully!", "danger")

    return redirect("/")

# -------------------------
# Borrow Book
# -------------------------
@app.route("/borrow/<int:id>")
def borrow(id):

    cursor.execute("SELECT * FROM books WHERE id=%s", (id,))
    book = cursor.fetchone()

    cursor.execute("SELECT * FROM members")
    members = cursor.fetchall()

    return render_template(
        "borrow_book.html",
        book=book,
        members=members
    )


# -------------------------
# Return Book (Preview)
# -------------------------

@app.route("/return_book/<int:id>")
def return_book(id):

    cursor.execute("""
        SELECT
            bh.id,
            bh.book_id,
            b.title,
            m.full_name,
            bh.borrow_date,
            bh.due_date
        FROM borrow_history bh
        JOIN books b
            ON bh.book_id = b.id
        JOIN members m
            ON bh.member_id = m.id
        WHERE bh.id=%s
    """, (id,))

    record = cursor.fetchone()

    # Current library date
    cursor.execute("SELECT library_date FROM system_settings WHERE id=1")
    today = cursor.fetchone()[0]

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
        fine=fine
    )

# -------------------------
# Confirm Return
# -------------------------

@app.route("/confirm_return/<int:id>", methods=["POST"])
def confirm_return(id):

    cursor.execute("""
        SELECT book_id, due_date
        FROM borrow_history
        WHERE id=%s
    """, (id,))

    record = cursor.fetchone()

    book_id = record[0]
    due_date = record[1]

    # Current library date
    cursor.execute("SELECT library_date FROM system_settings WHERE id=1")
    today = cursor.fetchone()[0]

    fine = 0

    if due_date and today > due_date:
        overdue_days = (today - due_date).days
        fine = overdue_days * 10

    cursor.execute("""
        UPDATE books
        SET quantity = quantity + 1
        WHERE id=%s
    """, (book_id,))

    cursor.execute("""
        UPDATE borrow_history
        SET
            return_date=%s,
            status='Returned',
            fine=%s
        WHERE id=%s
    """, (
        today,
        fine,
        id
    ))

    db.commit()

    flash(f"Book returned successfully! Fine Collected: ₹{fine}", "success")

    return redirect("/borrow_history")


# -------------------------
# Members
# -------------------------

@app.route("/members")
def members():

    cursor.execute("SELECT * FROM members")

    members = cursor.fetchall()

    return render_template(
        "members.html",
        members=members
    )



# -------------------------
# Add Member
# -------------------------

@app.route("/add_member")
def add_member():

    return render_template("add_member.html")


@app.route("/save_member", methods=["POST"])
def save_member():

    full_name = request.form["name"]
    email = request.form["email"]
    phone = request.form["phone"]

    sql = """
    INSERT INTO members(full_name, email, phone)
    VALUES(%s, %s, %s)
    """

    cursor.execute(sql, (full_name, email, phone))

    db.commit()

    flash("Member added successfully!", "success")

    return redirect("/members")

# -------------------------
# Edit Member
# -------------------------

@app.route("/edit_member/<int:id>")
def edit_member(id):

    cursor.execute("SELECT * FROM members WHERE id=%s", (id,))
    member = cursor.fetchone()

    return render_template("edit_member.html", member=member)


@app.route("/update_member/<int:id>", methods=["POST"])
def update_member(id):

    full_name = request.form["name"]
    email = request.form["email"]
    phone = request.form["phone"]

    sql = """
    UPDATE members
    SET full_name=%s,
        email=%s,
        phone=%s
    WHERE id=%s
    """

    cursor.execute(sql, (full_name, email, phone, id))

    db.commit()

    flash("Member updated successfully!", "warning")

    return redirect("/members")


# -------------------------
# Delete Member
# -------------------------

@app.route("/delete_member/<int:id>")
def delete_member(id):

    cursor.execute("DELETE FROM members WHERE id=%s", (id,))

    db.commit()

    flash("Member deleted successfully!", "danger")

    return redirect("/members")
# -------------------------
# Borrow History
# -------------------------
@app.route("/borrow_history")
def borrow_history():

    cursor.execute("""
        SELECT
            bh.id,
            b.title,
            m.full_name,
            bh.borrow_date,
            bh.due_date,
            bh.return_date,
            bh.status,
            bh.fine
                          
        FROM borrow_history bh
        JOIN books b
            ON bh.book_id = b.id
        JOIN members m
            ON bh.member_id = m.id
        ORDER BY bh.borrow_date DESC
    """)

    rows = cursor.fetchall()

    history = []

    cursor.execute("SELECT library_date FROM system_settings WHERE id=1")
    today = cursor.fetchone()[0]

    for row in rows:

        row = list(row)

        overdue_days = 0
        fine = row[7]

        if row[6] == "Borrowed" and row[4]:

            if today > row[4]:
               overdue_days = (today - row[4]).days
               fine = overdue_days * 10
               fine = overdue_days * 10

            cursor.execute("""
                UPDATE borrow_history
                SET fine=%s
                WHERE id=%s
            """, (
                fine,
                row[0]
            ))
               
        row[7] = fine
        row.append(overdue_days)

        history.append(row)
        print(history)

    db.commit()


    return render_template(
        "borrow_history.html",
        history=history
    )

# -------------------------
# Update Library Date
# -------------------------

@app.route("/update_library_date", methods=["POST"])
def update_library_date():

    if "admin" not in session:
        return redirect("/login")

    days = int(request.form["days"])

    cursor.execute("""
        UPDATE system_settings
        SET library_date = DATE_ADD(library_date, INTERVAL %s DAY)
        WHERE id=1
    """, (days,))

    db.commit()

    flash(f"Library date advanced by {days} day(s).", "success")

    return redirect("/")


# -------------------------
# Reset Library Date
# -------------------------

@app.route("/reset_library_date")
def reset_library_date():

    if "admin" not in session:
        return redirect("/login")

    cursor.execute("""
        UPDATE system_settings
        SET library_date = CURDATE()
        WHERE id=1
    """)

    db.commit()

    flash("Library date reset to today's date.", "warning")

    return redirect("/")

# -------------------------
# Admin Management
# -------------------------

@app.route("/admins")
def admins():

    if "admin" not in session:
        return redirect("/login")

    cursor.execute("""
        SELECT
            id,
            full_name,
            username,
            role,
            created_at
        FROM admins
        ORDER BY id
    """)

    admins = cursor.fetchall()

    return render_template(
        "admins.html",
        admins=admins
    )

# -------------------------
# Add Admin
# -------------------------

@app.route("/add_admin")
def add_admin():

    access = require_role(["Head Librarian"])

    if access:
        return access

    return render_template("add_admin.html")

@app.route("/save_admin", methods=["POST"])
def save_admin():

    access = require_role(["Head Librarian"])

    if access:
        return access

    full_name = request.form["full_name"]
    username = request.form["username"]
    password = request.form["password"]
    hashed_password = generate_password_hash(password)
    role = request.form["role"]

    # Check if username already exists
    cursor.execute(
        "SELECT id FROM admins WHERE username=%s",
        (username,)
    )

    if cursor.fetchone():

        flash("Username already exists!", "danger")

        return redirect("/add_admin")

    cursor.execute("""
    INSERT INTO admins
    (full_name, username, password, role)
    VALUES(%s,%s,%s,%s)
""",(
    full_name,
    username,
    hashed_password,
    role
))

    db.commit()

    flash("New admin created successfully!", "success")

    return redirect("/admins")

# -------------------------
# Edit Admin
# -------------------------

@app.route("/edit_admin/<int:id>")
def edit_admin(id):

    access = require_role(["Head Librarian"])

    if access:
        return access

    cursor.execute(
        "SELECT * FROM admins WHERE id=%s",
        (id,)
    )

    admin = cursor.fetchone()

    return render_template(
        "edit_admin.html",
        admin=admin
    )


@app.route("/update_admin/<int:id>", methods=["POST"])
def update_admin(id):

    access = require_role(["Head Librarian"])

    if access:
        return access

    full_name = request.form["full_name"]
    username = request.form["username"]
    role = request.form["role"]

    cursor.execute("""
        UPDATE admins
        SET
            full_name=%s,
            username=%s,
            role=%s
        WHERE id=%s
    """, (
        full_name,
        username,
        role,
        id
    ))

    db.commit()

    flash(
        "Admin updated successfully!",
        "success"
    )

    return redirect("/admins")

# -------------------------
# Delete Admin
# -------------------------

@app.route("/delete_admin/<int:id>")
def delete_admin(id):

    access = require_role(["Head Librarian"])

    if access:
        return access

    # Get selected admin
    cursor.execute("""
        SELECT username, role
        FROM admins
        WHERE id=%s
    """, (id,))

    admin = cursor.fetchone()

    if not admin:

        flash("Admin not found!", "danger")

        return redirect("/admins")

    username = admin[0]
    role = admin[1]

    # Prevent deleting yourself
    if username == session["admin"]:

        flash("You cannot delete your own account!", "danger")

        return redirect("/admins")

    # Prevent deleting the last Head Librarian
    if role == "Head Librarian":

        cursor.execute("""
            SELECT COUNT(*)
            FROM admins
            WHERE role='Head Librarian'
        """)

        total_heads = cursor.fetchone()[0]

        if total_heads <= 1:

            flash(
                "At least one Head Librarian must remain!",
                "danger"
            )

            return redirect("/admins")

    # Delete admin
    cursor.execute(
        "DELETE FROM admins WHERE id=%s",
        (id,)
    )

    db.commit()

    flash(
        "Admin deleted successfully!",
        "success"
    )

    return redirect("/admins")

# -------------------------
# Activity Logs
# -------------------------

@app.route("/activity_logs")
def activity_logs():

    access = require_role(["Head Librarian"])

    if access:
        return access

    search = request.args.get("search")

    if search:

        cursor.execute("""
            SELECT
                username,
                role,
                action,
                log_time
            FROM activity_logs
            WHERE
                username LIKE %s
                OR action LIKE %s
            ORDER BY log_time DESC
        """, (
            f"%{search}%",
            f"%{search}%"
        ))

    else:

        cursor.execute("""
            SELECT
                username,
                role,
                action,
                log_time
            FROM activity_logs
            ORDER BY log_time DESC
        """)

    logs = cursor.fetchall()

    return render_template(
        "activity_logs.html",
        logs=logs
    )

# -------------------------
# Reports
# -------------------------

@app.route("/reports")
def reports():

    access = require_role(["Head Librarian", "Librarian"])

    if access:
        return access

    # Total books
    cursor.execute("SELECT COUNT(*) FROM books")
    total_books = cursor.fetchone()[0]

    # Total copies
    cursor.execute("SELECT SUM(quantity) FROM books")
    total_quantity = cursor.fetchone()[0] or 0

    # Total members
    cursor.execute("SELECT COUNT(*) FROM members")
    total_members = cursor.fetchone()[0]

    # Borrowed books
    cursor.execute("""
        SELECT COUNT(*)
        FROM borrow_history
        WHERE status='Borrowed'
    """)
    borrowed_books = cursor.fetchone()[0]

    # Returned books
    cursor.execute("""
        SELECT COUNT(*)
        FROM borrow_history
        WHERE status='Returned'
    """)
    returned_books = cursor.fetchone()[0]

    # Total fines collected
    cursor.execute("""
        SELECT SUM(fine)
        FROM borrow_history
    """)
    total_fines = cursor.fetchone()[0] or 0

    # Overdue books
    cursor.execute("""
        SELECT COUNT(*)
        FROM borrow_history
        WHERE status='Borrowed'
        AND due_date < CURDATE()
    """)
    overdue_books = cursor.fetchone()[0]

    return render_template(
        "reports.html",
        total_books=total_books,
        total_quantity=total_quantity,
        total_members=total_members,
        borrowed_books=borrowed_books,
        returned_books=returned_books,
        overdue_books=overdue_books,
        total_fines=total_fines
    )


if __name__ == "__main__":
    app.run(debug=True)