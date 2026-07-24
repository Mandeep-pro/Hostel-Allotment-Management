from __future__ import annotations

import random
import re
from pathlib import Path
from functools import wraps
import os

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
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

DEMO_STUDENTS = [
    ("Aarav Sharma", "016"),
    ("Diya Verma", "028"),
    ("Kabir Khan", "088"),
    ("Meera Iyer", "104"),
    ("Rohan Gupta", "119"),
    ("Sana Mir", "127"),
    ("Arjun Singh", "143"),
    ("Isha Kapoor", "156"),
    ("Vivaan Patel", "172"),
    ("Ananya Das", "184"),
    ("Reyansh Jain", "203"),
    ("Zoya Ali", "219"),
]


class Student(database.Model):
    id = database.Column(database.Integer, primary_key=True)
    full_name = database.Column(database.String(120), nullable=False)
    enrollment_number = database.Column(database.String(40), nullable=False, unique=True, index=True)
    room_id = database.Column(database.Integer, database.ForeignKey("room.id"), nullable=True)


class Room(database.Model):
    id = database.Column(database.Integer, primary_key=True)
    room_number = database.Column(database.String(20), nullable=False, unique=True)
    hostel_name = database.Column(database.String(80), nullable=False, default="Manasbal")
    students = database.relationship("Student", backref="room", lazy=True)


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
        name = request.form.get("full_name", "").strip()
        enrollment = request.form.get("enrollment_number", "").strip().upper()

        if not name or not enrollment:
            flash("Please enter both your name and enrollment number.", "error")
        elif not NAME_PATTERN.fullmatch(name):
            flash("Name can contain letters and spaces only.", "error")
        elif not ENROLLMENT_PATTERN.fullmatch(enrollment):
            flash("Enrollment number must contain exactly three digits (for example, 016).", "error")
        else:
            database.session.add(Student(full_name=name, enrollment_number=enrollment))
            try:
                database.session.commit()
                flash("Registration saved successfully.", "success")
                return redirect(url_for("my_allotment"))
            except IntegrityError:
                database.session.rollback()
                flash("This enrollment number has already been registered.", "error")

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
    rooms = Room.query.order_by(Room.room_number).all()
    unassigned_students = Student.query.filter_by(room_id=None).order_by(Student.full_name).all()
    return render_template(
        "admin_dashboard.html",
        rooms=rooms,
        unassigned_students=unassigned_students,
        total_students=Student.query.count(),
    )


@app.post("/admin/shuffle")
@admin_required
def shuffle_rooms():
    students = Student.query.order_by(Student.id).all()
    random.shuffle(students)

    Room.query.delete()
    database.session.flush()

    complete_room_count = len(students) // 6
    for room_index in range(complete_room_count):
        room = Room(room_number=f"M-{room_index + 1:03d}", hostel_name="Manasbal")
        database.session.add(room)
        for student in students[room_index * 6 : (room_index + 1) * 6]:
            student.room = room

    for student in students[complete_room_count * 6 :]:
        student.room = None

    database.session.commit()
    if complete_room_count:
        flash(f"Created {complete_room_count} randomized Manasbal room(s), with exactly six students each.", "success")
    else:
        flash("At least six registered students are required to create a room.", "error")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/reset")
@admin_required
def reset_assignments():
    Room.query.delete()
    database.session.commit()
    flash("All room assignments were cleared. Student registrations were kept.", "success")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/load-demo-students")
@admin_required
def load_demo_students():
    existing_enrollments = {student.enrollment_number for student in Student.query.all()}
    added_count = 0
    for full_name, enrollment_number in DEMO_STUDENTS:
        if enrollment_number not in existing_enrollments:
            database.session.add(Student(full_name=full_name, enrollment_number=enrollment_number))
            added_count += 1
    database.session.commit()
    flash(f"Added {added_count} dummy student record(s).", "success")
    return redirect(url_for("admin_dashboard"))


with app.app_context():
    database.create_all()


if __name__ == "__main__":
    app.run(debug=True)
