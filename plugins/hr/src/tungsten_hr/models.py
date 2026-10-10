"""Tables of the HR plugin. Panel users are stored by id as a string, so any user model works."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> dt.datetime:
    return dt.datetime.now()


class HRBase(DeclarativeBase):
    pass


class Department(HRBase):
    __tablename__ = "tungsten_hr_departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    color: Mapped[str] = mapped_column(String(20), default="gray")
    #: the employee who heads it (approves leave when an employee has no manager)
    head_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_hr_employees.id", ondelete="SET NULL", use_alter=True), nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    head: Mapped[Employee | None] = relationship(foreign_keys=[head_id], post_update=True)
    employees: Mapped[list[Employee]] = relationship(back_populates="department", foreign_keys="Employee.department_id")

    def __str__(self) -> str:
        return self.name


class Employee(HRBase):
    __tablename__ = "tungsten_hr_employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: the code people quote, like EMP-0007
    code: Mapped[str | None] = mapped_column(String(30), nullable=True, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    photo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_hr_departments.id", ondelete="SET NULL"), nullable=True, index=True)
    job_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_hr_employees.id", ondelete="SET NULL"), nullable=True, index=True)
    #: the person's number on the biometric machine (the "user ID" or "PIN" punched in)
    biometric_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    #: the panel user who logs in as this employee (for check-in and own leave)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    #: full_time, part_time, contract, intern
    employment_type: Mapped[str] = mapped_column(String(20), default="full_time")
    #: active, probation, notice, left
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    joined_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    left_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    birth_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    salary: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    emergency_contact: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: bank, ID numbers and anything else, as key: value
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    documents: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    department: Mapped[Department | None] = relationship(
        back_populates="employees", foreign_keys=[department_id], lazy="joined")
    manager: Mapped[Employee | None] = relationship(remote_side=[id], foreign_keys=[manager_id])
    attendance: Mapped[list[Attendance]] = relationship(
        back_populates="employee", cascade="all, delete-orphan", order_by="Attendance.date.desc()")
    leave_requests: Mapped[list[LeaveRequest]] = relationship(
        back_populates="employee", cascade="all, delete-orphan", order_by="LeaveRequest.start_date.desc()")

    @property
    def name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p)

    @property
    def is_active(self) -> bool:
        return self.status != "left"

    def __str__(self) -> str:
        return self.name


class Attendance(HRBase):
    """One employee's day: present, absent, half day, on leave..."""

    __tablename__ = "tungsten_hr_attendance"
    __table_args__ = (UniqueConstraint("employee_id", "date", name="uq_tungsten_hr_attendance_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("tungsten_hr_employees.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    #: present, absent, half_day, leave, holiday, remote
    status: Mapped[str] = mapped_column(String(20), default="present", index=True)
    check_in: Mapped[dt.time | None] = mapped_column(Time, nullable=True)
    check_out: Mapped[dt.time | None] = mapped_column(Time, nullable=True)
    #: hours worked, filled from check in and check out
    hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_late: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: panel, self (check-in button), leave, import, api
    source: Mapped[str] = mapped_column(String(20), default="panel")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    employee: Mapped[Employee] = relationship(back_populates="attendance", lazy="joined")

    def __str__(self) -> str:
        return f"{self.employee} {self.date:%d %b %Y}" if self.employee else str(self.date)


class LeaveType(HRBase):
    """Casual, Sick, Earned... with how many days a year each employee gets."""

    __tablename__ = "tungsten_hr_leave_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    #: days per year; None means no limit
    days_per_year: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=True)
    #: let people ask for more days than they have left
    allow_negative: Mapped[bool] = mapped_column(Boolean, default=False)
    color: Mapped[str] = mapped_column(String(20), default="info")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    def __str__(self) -> str:
        return self.name


class LeaveRequest(HRBase):
    __tablename__ = "tungsten_hr_leave_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("tungsten_hr_employees.id", ondelete="CASCADE"), index=True)
    leave_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_hr_leave_types.id", ondelete="SET NULL"), nullable=True, index=True)
    start_date: Mapped[dt.date] = mapped_column(Date, index=True)
    end_date: Mapped[dt.date] = mapped_column(Date, index=True)
    half_day: Mapped[bool] = mapped_column(Boolean, default=False)
    #: working days asked for (weekends and holidays left out)
    days: Mapped[float] = mapped_column(Float, default=0)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: pending, approved, rejected, cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)

    employee: Mapped[Employee] = relationship(back_populates="leave_requests", lazy="joined")
    leave_type: Mapped[LeaveType | None] = relationship(lazy="joined")

    def __str__(self) -> str:
        kind = self.leave_type.name if self.leave_type else "Leave"
        return f"{kind}: {self.employee} {self.start_date:%d %b}" if self.employee else kind


class Holiday(HRBase):
    __tablename__ = "tungsten_hr_holidays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    date: Mapped[dt.date] = mapped_column(Date, index=True, unique=True)
    #: optional holidays don't count as days off when leave is counted
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)

    def __str__(self) -> str:
        return f"{self.name} ({self.date:%d %b %Y})"


class BiometricDevice(HRBase):
    """A fingerprint / face machine (eSSL, ZKTeco...). It pushes punches, or the panel pulls them."""

    __tablename__ = "tungsten_hr_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    #: the machine's serial number (SN), sent with every push
    serial_number: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    #: for pulling over the office network
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    port: Mapped[int] = mapped_column(Integer, default=4370)
    password: Mapped[int] = mapped_column(Integer, default=0)
    #: punches are only taken from active machines
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_punch_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    def __str__(self) -> str:
        return self.name


class Punch(HRBase):
    """One raw punch from a machine, the API or a file. Attendance is worked out from punches."""

    __tablename__ = "tungsten_hr_punches"
    __table_args__ = (UniqueConstraint("person", "punched_at", name="uq_tungsten_hr_punch"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: what the machine or file sent: the machine ID or the employee code
    person: Mapped[str] = mapped_column(String(50), index=True)
    punched_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    #: None until a person with this machine ID or code is found
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_hr_employees.id", ondelete="CASCADE"), nullable=True, index=True)
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_hr_devices.id", ondelete="SET NULL"), nullable=True, index=True)
    #: push (machine sent it), pull (panel fetched it), api, import
    source: Mapped[str] = mapped_column(String(20), default="push")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    employee: Mapped[Employee | None] = relationship(lazy="joined")
    device: Mapped[BiometricDevice | None] = relationship(lazy="joined")

    def __str__(self) -> str:
        return f"{self.person} {self.punched_at:%d %b %H:%M}"
