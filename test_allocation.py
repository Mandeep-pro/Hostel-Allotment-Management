import os
import tempfile
import unittest

from app import app, database, Student, Room


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_hostel_allotment.db")
        app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=f"sqlite:///{self.db_path}")
        self.app_context = app.app_context()
        self.app_context.push()
        database.drop_all()
        database.create_all()

    def tearDown(self):
        database.session.remove()
        database.drop_all()
        self.app_context.pop()
        self.temp_dir.cleanup()

    def test_allocation_uses_six_students_per_room_and_prevents_duplicates(self):
        for idx in range(12):
            student = Student(full_name=f"Student {idx}", enrollment_number=f"{idx:03d}", hostel_name="Manasbal")
            database.session.add(student)
        database.session.commit()

        # Simulate the admin allocation flow.
        from app import create_rooms_for_all_students

        rooms = create_rooms_for_all_students()

        self.assertEqual(len(rooms), 2)
        self.assertEqual(len(rooms[0].students), 6)
        self.assertEqual(len(rooms[1].students), 6)

        # No student can appear in more than one room.
        assigned_student_ids = []
        for room in rooms:
            assigned_student_ids.extend(student.id for student in room.students)
        self.assertEqual(len(assigned_student_ids), len(set(assigned_student_ids)))


if __name__ == "__main__":
    unittest.main()
