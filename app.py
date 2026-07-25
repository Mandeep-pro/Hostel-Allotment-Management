from __future__ import annotations

import os
import re
from collections import Counter
from functools import wraps
from io import BytesIO
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_file, session, url_for
from flask_sqlalchemy import SQLAlchemy
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

BASE_DIRECTORY = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIRECTORY / "hostel_allotment.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-secret-key-before-deployment"
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DATABASE_PATH.as_posix()}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["ADMIN_USERNAME"] = os.environ.get("HOSTEL_ADMIN_USERNAME", "admin")
app.config["ADMIN_PASSWORD"] = os.environ.get("HOSTEL_ADMIN_PASSWORD", "manasbal123")
database = SQLAlchemy(app)
ENROLLMENT_PATTERN = re.compile(r"^\d{3}$")
NAME_PATTERN = re.compile(r"^[A-Za-z]+(?: [A-Za-z]+)*$")
HOSTELS = ("Manasbal", "Mansar")
ROOM_NUMBER_POOL = [str(number) for number in range(101, 126)] + [str(number) for number in range(201, 226)]
ROOM_CAPACITY = 6
ROOM_PREFIXES = {"Manasbal": "MB", "Mansar": "MR"}


class Student(database.Model):
    id = database.Column(database.Integer, primary_key=True)
    full_name = database.Column(database.String(120), nullable=False)
    enrollment_number = database.Column(database.String(40), nullable=False, unique=True, index=True)
    hostel_name = database.Column(database.String(80), nullable=False, default="Manasbal")
    preferred_room_number = database.Column(database.String(20), nullable=True)
    room_id = database.Column(database.Integer, database.ForeignKey("room.id"), nullable=True)


class Room(database.Model):
    id = database.Column(database.Integer, primary_key=True)
    room_number = database.Column(database.String(20), nullable=False)
    hostel_name = database.Column(database.String(80), nullable=False, default="Manasbal")
    students = database.relationship("Student", backref="room", lazy=True)

    @property
    def display_room_number(self):
        return self.room_number


def create_rooms_for_all_students():
    Student.query.update({Student.room_id: None})
    Room.query.delete()
    database.session.flush()

    students = Student.query.order_by(Student.id).all()
    if len(students) < ROOM_CAPACITY:
        database.session.commit()
        return []

    created_rooms = []
    for hostel_name in HOSTELS:
        hostel_students = [student for student in students if student.hostel_name == hostel_name]
        if not hostel_students:
            continue

        preferred_groups = {}
        unassigned_students = []
        for student in hostel_students:
            preferred_room_number = student.preferred_room_number
            if preferred_room_number in ROOM_NUMBER_POOL:
                preferred_groups.setdefault(preferred_room_number, []).append(student)
            else:
                unassigned_students.append(student)

        room_count = (len(hostel_students) + ROOM_CAPACITY - 1) // ROOM_CAPACITY
        for room_index in range(room_count):
            room_number = ROOM_NUMBER_POOL[room_index]
            prefix = ROOM_PREFIXES[hostel_name]
            room = Room(room_number=f"{prefix}-{room_number}", hostel_name=hostel_name)
            database.session.add(room)
            created_rooms.append(room)

            room_students = []
            if room_number in preferred_groups:
                room_students.extend(preferred_groups[room_number])

            if len(room_students) < ROOM_CAPACITY and unassigned_students:
                needed = ROOM_CAPACITY - len(room_students)
                room_students.extend(unassigned_students[:needed])
                unassigned_students = unassigned_students[needed:]

            if len(room_students) > ROOM_CAPACITY:
                room_students = room_students[:ROOM_CAPACITY]

            for student in room_students:
                student.room = room

    database.session.commit()
    return created_rooms


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Please sign in as an administrator.", "error")
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped_view


@app.get("/")
def welcome_page():
    return render_template("welcome.html")


@app.route("/register", methods=["GET", "POST"])
def student_registration():
    if request.method == "POST":
        hostel_name = request.form.get("hostel_name", "").strip()
        preferred_room = request.form.get("preferred_room", "").strip()
        student_records = []

        if hostel_name not in HOSTELS:
            flash("Please choose either Manasbal or Mansar hostel.", "error")
            return render_template("register_student.html")

        if preferred_room not in ROOM_NUMBER_POOL:
            flash("Preferred room must be between 101 and 125 or 201 and 225.", "error")
            return render_template("register_student.html")

        for index in range(1, 7):
            name = request.form.get(f"student_name_{index}", "").strip()
            enrollment = request.form.get(f"enrollment_number_{index}", "").strip().upper()
            if not name or not enrollment:
                flash("Please complete all six student rows before submitting your registration group.", "error")
                return render_template("register_student.html")
            if not NAME_PATTERN.fullmatch(name):
                flash(f"Name for student {index} can contain letters and spaces only.", "error")
                return render_template("register_student.html")
            if not ENROLLMENT_PATTERN.fullmatch(enrollment):
                flash(f"Enrollment number for student {index} must contain exactly three digits.", "error")
                return render_template("register_student.html")
            student_records.append((name, enrollment))

        enrollment_counter = Counter(enrollment for _, enrollment in student_records)
        duplicate_enrollments = [enrollment for enrollment, count in enrollment_counter.items() if count > 1]
        if duplicate_enrollments:
            flash("Each enrollment number must be unique within a registration group.", "error")
            return render_template("register_student.html")

        existing_enrollments = {student.enrollment_number for student in Student.query.all()}
        for _, enrollment in student_records:
            if enrollment in existing_enrollments:
                flash(f"The enrollment number {enrollment} is already registered.", "error")
                return render_template("register_student.html")

        for name, enrollment in student_records:
            database.session.add(
                Student(
                    full_name=name,
                    enrollment_number=enrollment,
                    hostel_name=hostel_name,
                    preferred_room_number=preferred_room,
                )
            )
        try:
            database.session.commit()
            flash("Registration group saved successfully. The administrator can now generate the room allotment PDF.", "success")
            return redirect(url_for("my_allotment"))
        except IntegrityError:
            database.session.rollback()
            flash("A registration group could not be saved because one enrollment already exists.", "error")

    return render_template("register_student.html")


@app.route("/my-allotment", methods=["GET", "POST"])
def my_allotment():
    student = None
    if request.method == "POST":
        enrollment = request.form.get("enrollment_number", "").strip()
        if not ENROLLMENT_PATTERN.fullmatch(enrollment):
            flash("Enter your three-digit enrollment number.", "error")
        else:
            student = Student.query.filter_by(enrollment_number=enrollment).first()
            if not student:
                flash("No student registration was found for that enrollment number.", "error")

    roommates = []
    if student and student.room:
        roommates = sorted(
            [roommate for roommate in student.room.students if roommate.id != student.id],
            key=lambda roommate: roommate.full_name,
        )
    return render_template("student_allotment.html", student=student, roommates=roommates)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username == app.config["ADMIN_USERNAME"] and password == app.config["ADMIN_PASSWORD"]:
            session.clear()
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Incorrect administrator username or password.", "error")
    return render_template("admin_login.html")


@app.post("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    flash("Administrator signed out.", "success")
    return redirect(url_for("welcome_page"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    rooms = Room.query.order_by(Room.hostel_name, Room.room_number).all()
    assigned_students = Student.query.filter(Student.room_id.isnot(None)).order_by(Student.full_name).all()
    unassigned_students = Student.query.filter_by(room_id=None).order_by(Student.full_name).all()
    students = Student.query.order_by(Student.full_name).all()
    return render_template(
        "admin_dashboard.html",
        rooms=rooms,
        assigned_students=assigned_students,
        unassigned_students=unassigned_students,
        students=students,
        total_students=Student.query.count(),
    )


@app.post("/admin/generate-allotment")
@admin_required
def generate_allotment():
    created_rooms = create_rooms_for_all_students()
    if not created_rooms:
        flash("At least six registered students are required to generate a room allotment.", "error")
        return redirect(url_for("admin_dashboard"))

    flash("Room allotment generated successfully. The PDF report now lists occupied and empty rooms.", "success")
    return export_pdf()


@app.post("/admin/reset")
@admin_required
def reset_assignments():
    Student.query.update({Student.room_id: None})
    Room.query.delete()
    database.session.commit()
    flash("All room assignments were cleared. Student registrations were kept.", "success")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/students/delete")
@admin_required
def delete_students():
    student_ids = {int(student_id) for student_id in request.form.getlist("student_ids") if student_id.isdigit()}
    if not student_ids:
        flash("Select at least one student to remove.", "error")
        return redirect(url_for("admin_dashboard"))

    students = Student.query.filter(Student.id.in_(student_ids)).all()
    if not students:
        flash("The selected student records were not found.", "error")
        return redirect(url_for("admin_dashboard"))

    Student.query.update({Student.room_id: None})
    Room.query.delete()
    for student in students:
        database.session.delete(student)
    database.session.commit()
    flash("Removed the selected student records. Room assignments were cleared.", "success")
    return redirect(url_for("admin_dashboard"))


@app.get("/admin/allotment-report.pdf")
@admin_required
def export_pdf():
    rooms = Room.query.order_by(Room.hostel_name, Room.room_number).all()
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=letter, title="Hostel Allotment Report")
    styles = getSampleStyleSheet()
    story = [Paragraph("Hostel allotment report", styles["Title"]), Spacer(1, 12)]

    for hostel_name in HOSTELS:
        hostel_rooms = [room for room in rooms if room.hostel_name == hostel_name]
        if not hostel_rooms:
            continue
        story.append(Paragraph(hostel_name, styles["Heading2"]))
        rows = [["Room", "Students"]]
        for room in hostel_rooms:
            occupants = []
            for student in sorted(room.students, key=lambda item: item.full_name):
                occupants.append(f"{student.full_name} ({student.enrollment_number})")
            rows.append([room.display_room_number, ", ".join(occupants) if occupants else "Empty"])
        table = Table(rows, repeatRows=1, colWidths=[120, 420])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#007c74")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
                    ("PADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 12))

    document.build(story)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name="hostel_allotment_report.pdf")


with app.app_context():
    database.create_all()
    student_columns = {column[1] for column in database.session.execute(text("PRAGMA table_info(student)"))}
    if "hostel_name" not in student_columns:
        database.session.execute(text("ALTER TABLE student ADD COLUMN hostel_name VARCHAR(80) NOT NULL DEFAULT 'Manasbal'"))
        database.session.commit()
    if "preferred_room_number" not in student_columns:
        database.session.execute(text("ALTER TABLE student ADD COLUMN preferred_room_number VARCHAR(20)"))
        database.session.commit()


if __name__ == "__main__":
    app.run(debug=True)
