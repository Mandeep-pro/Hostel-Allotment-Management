from __future__ import annotations

import random
import re
from pathlib import Path
from functools import wraps
import os

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text

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

class Student(database.Model):
    id = database.Column(database.Integer, primary_key=True)
    full_name = database.Column(database.String(120), nullable=False)
    enrollment_number = database.Column(database.String(40), nullable=False, unique=True, index=True)
    hostel_name = database.Column(database.String(80), nullable=False, default="Manasbal")
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
        hostel_name = request.form.get("hostel_name", "").strip()

        if not name or not enrollment:
            flash("Please enter both your name and enrollment number.", "error")
        elif not NAME_PATTERN.fullmatch(name):
            flash("Name can contain letters and spaces only.", "error")
        elif not ENROLLMENT_PATTERN.fullmatch(enrollment):
            flash("Enrollment number must contain exactly three digits (for example, 016).", "error")
        elif hostel_name not in HOSTELS:
            flash("Please choose either Manasbal or Mansar hostel.", "error")
        else:
            database.session.add(Student(full_name=name, enrollment_number=enrollment, hostel_name=hostel_name))
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
    students = Student.query.order_by(Student.full_name).all()
    return render_template(
        "admin_dashboard.html",
        rooms=rooms,
        unassigned_students=unassigned_students,
        students=students,
        total_students=Student.query.count(),
    )


@app.post("/admin/shuffle")
@admin_required
def shuffle_rooms():
    Student.query.update({Student.room_id: None})
    Room.query.delete()
    database.session.flush()

    created_rooms = []
    for hostel_name, prefix in (("Manasbal", "M"), ("Mansar", "S")):
        students = Student.query.filter_by(hostel_name=hostel_name).order_by(Student.id).all()
        random.shuffle(students)
        complete_room_count = len(students) // 6
        for room_index in range(complete_room_count):
            room = Room(room_number=f"{prefix}-{room_index + 1:03d}", hostel_name=hostel_name)
            database.session.add(room)
            created_rooms.append(hostel_name)
            for student in students[room_index * 6 : (room_index + 1) * 6]:
                student.room = room

        for student in students[complete_room_count * 6 :]:
            student.room = None

    database.session.commit()
    if created_rooms:
        summary = ", ".join(f"{hostel}: {created_rooms.count(hostel)}" for hostel in HOSTELS if hostel in created_rooms)
        flash(f"Created randomized rooms with exactly six students each ({summary}).", "success")
    else:
        flash("At least six registered students are required to create a room.", "error")
    return redirect(url_for("admin_dashboard"))


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
    flash(f"Removed {len(students)} student(s). Room assignments were cleared; shuffle again to re-allot rooms.", "success")
    return redirect(url_for("admin_dashboard"))


with app.app_context():
    database.create_all()
    student_columns = {column[1] for column in database.session.execute(text("PRAGMA table_info(student)"))}
    if "hostel_name" not in student_columns:
        database.session.execute(text("ALTER TABLE student ADD COLUMN hostel_name VARCHAR(80) NOT NULL DEFAULT 'Manasbal'"))
        database.session.commit()


if __name__ == "__main__":
    app.run(debug=True)
