from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from sqlalchemy import select
from tungsten_hr import Attendance, BiometricDevice, Employee, Punch, link_punches, pull_all
from tungsten_hr.resources import PunchImporter

from tungsten.importexport import read_table, run_import

DAY = dt.date(2026, 11, 2)


def session(panel):
    db = panel.db()
    db.info["tungsten_panel"] = panel
    return db


def set_machine_id(panel, employee_id, value):
    with session(panel) as db:
        db.get(Employee, employee_id).biometric_id = value
        db.commit()


def day_row(panel, employee_id, day=DAY):
    with session(panel) as db:
        return db.scalars(select(Attendance).where(Attendance.employee_id == employee_id,
                                                   Attendance.date == day)).first()


def test_machine_push(client, panel):
    set_machine_id(panel, 2, "7")
    http = client.client
    # a new machine waits until someone turns it on
    r = http.get("/iclock/cdata", params={"SN": "CQZ123", "options": "all"})
    assert r.status_code == 403
    with session(panel) as db:
        device = db.scalars(select(BiometricDevice)).one()
        assert device.serial_number == "CQZ123" and not device.is_active
        device.is_active = True
        db.commit()
    r = http.get("/iclock/cdata", params={"SN": "CQZ123", "options": "all"})
    assert r.status_code == 200 and "GET OPTION FROM: CQZ123" in r.text and "ATTLOGStamp" in r.text
    body = (f"7\t{DAY} 09:05:12\t0\t1\t0\t0\n"
            f"7\t{DAY} 18:10:00\t1\t1\t0\t0\n"
            f"99\t{DAY} 09:40:00\t0\t1\t0\t0\n")
    r = http.post("/iclock/cdata", params={"SN": "CQZ123", "table": "ATTLOG", "Stamp": "1"}, content=body)
    assert r.status_code == 200 and r.text == "OK: 3"
    r = http.post("/iclock/cdata.aspx", params={"SN": "CQZ123", "table": "ATTLOG"}, content=body)  # sent again
    assert r.text == "OK: 3"
    assert http.get("/iclock/getrequest", params={"SN": "CQZ123"}).text == "OK"
    row = day_row(panel, 2)
    assert row.check_in == dt.time(9, 5, 12) and row.check_out == dt.time(18, 10) and row.status == "present"
    assert row.hours == 9.08 and row.source == "device"
    with session(panel) as db:
        assert len(db.scalars(select(Punch)).all()) == 3
        unknown = db.scalars(select(Punch).where(Punch.person == "99")).one()
        assert unknown.employee_id is None
        assert db.scalars(select(BiometricDevice)).one().last_punch_at == dt.datetime(2026, 11, 2, 18, 10)
    # the punch from ID 99 is used once Asha gets that machine ID
    with session(panel) as db:
        asha = db.get(Employee, 1)
        asha.biometric_id = "99"
        assert link_punches(db, asha) == 1
        db.commit()
    row = day_row(panel, 1)
    assert row.check_in == dt.time(9, 40) and row.is_late


def test_pull_from_machine(panel):
    class FakeZK:
        def __init__(self, ip, port, timeout, password, ommit_ping):
            assert (ip, port) == ("192.168.1.201", 4370)

        def connect(self):
            return self

        def get_attendance(self):
            return [SimpleNamespace(user_id="7", timestamp=dt.datetime(2026, 11, 2, 9, 0)),
                    SimpleNamespace(user_id="7", timestamp=dt.datetime(2026, 11, 2, 13, 0))]

        def disconnect(self):
            pass

    set_machine_id(panel, 2, "7")
    with session(panel) as db:
        db.add(BiometricDevice(name="Gate", ip_address="192.168.1.201"))
        db.commit()
        assert pull_all(db, FakeZK) == {"Gate": 2}
        assert pull_all(db, FakeZK) == {"Gate": 0}  # only newer punches are kept
    row = day_row(panel, 2)
    assert row.check_in == dt.time(9) and row.check_out == dt.time(13) and row.status == "present"


def test_api(client, panel):
    http = client.client
    r = http.post("/admin/api/hr/punches", json={"employee": "EMP-0002", "time": f"{DAY} 10:00"})
    assert r.status_code == 401
    r = http.post("/admin/api/hr/punches", headers={"X-HR-Token": "hr-token"}, json={"punches": [
        {"employee": "EMP-0002", "time": f"{DAY} 09:20"},
        {"employee": "EMP-0002", "time": f"{DAY}T12:30:00"},
        {"employee": "EMP-0002", "time": f"{DAY} 09:20"},
        {"employee": "X1", "time": f"{DAY} 09:00"},
        {"employee": "EMP-0002", "time": "yesterday"},
    ]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["saved"] == 3 and data["repeated"] == 1 and data["unknown_people"] == ["X1"]
    assert len(data["errors"]) == 1 and "Can't read the time" in data["errors"][0]["error"]
    row = day_row(panel, 2)
    assert row.check_in == dt.time(9, 20) and row.check_out == dt.time(12, 30)
    assert row.status == "half_day"  # 3.17 hours


def test_csv_upload(panel):
    csv = (f"User ID,Punch Time\nEMP-0001,{DAY} 08:55:00\nEMP-0001,02-11-2026 17:30\n"
           f"EMP-0001,{DAY} 08:55:00\nnobody,{DAY} 10:00\n,{DAY} 10:00\n").encode()
    with session(panel) as db:
        ctx = SimpleNamespace(db=db, panel=panel, user=None, tenant=None)
        created, updated, failures = run_import(ctx, PunchImporter, read_table(csv, "punches.csv"))
    assert (created, updated, len(failures)) == (3, 1, 1)
    row = day_row(panel, 1)
    assert row.check_in == dt.time(8, 55) and row.check_out == dt.time(17, 30) and not row.is_late


def test_screens(admin):
    for url in ("/admin/biometric-devices", "/admin/punches", "/admin/employees/create"):
        r = admin.get(url)
        assert r.status_code == 200, (url, r.text[:300])
    assert "Upload punches" in admin.get("/admin/punches").text
    assert "Machine ID" in admin.get("/admin/employees/create").text
