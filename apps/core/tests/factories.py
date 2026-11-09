"""Shared test helpers: load the real institutional configuration and build small fixtures."""
import datetime
import io
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.utils import timezone

from apps.academics.models import AcademicSession, Course, CourseAllocation, Programme, Semester
from apps.accounts.models import StaffProfile, User
from apps.students import services as stu
from apps.students.models import StudentStatus


def load_institution():
    call_command("setup_institution", stdout=io.StringIO())


def session_and_semester(term=1, current=True):
    today = timezone.localdate()
    sess, _ = AcademicSession.objects.get_or_create(name="2026/2027", defaults={
        "start_date": today - datetime.timedelta(days=30), "end_date": today + datetime.timedelta(days=300), "is_current": current})
    sem, _ = Semester.objects.get_or_create(session=sess, term=term, defaults={
        "registration_opens": today - datetime.timedelta(days=10), "registration_closes": today + datetime.timedelta(days=20),
        "is_current": current})
    return sess, sem


def staff(username, role=None, superuser=False, dept=None):
    u = User.objects.create_user(username=username, password="Passw0rd!x", user_type="staff", email=f"{username}@t.invalid",
                                 is_superuser=superuser, is_staff=superuser)
    if role:
        u.groups.add(Group.objects.get(name=role))
    StaffProfile.objects.create(user=u, staff_id=username.upper(), department=dept)
    return u


def student(code="PHT", year=1, actor=None, **extra):
    prog = Programme.objects.get(code=code)
    sess, _ = session_and_semester()
    data = {"first_name": extra.pop("first_name", "Test"), "last_name": extra.pop("last_name", "Student"), "gender": "F"}
    s, _ = stu.create_student(data, actor, programme=prog, session=sess, current_year=year,
                              status=StudentStatus.get("active"), password="Passw0rd!x")
    return s


def allocate(course, semester, lecturer):
    return CourseAllocation.objects.create(course=course, semester=semester, lecturer=lecturer)


def courses(code, year, term):
    return list(Course.objects.filter(programme__code=code, year=year, term=term))


D = Decimal
