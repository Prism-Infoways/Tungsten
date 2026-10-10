"""Biometric machines: punches become attendance.

Three ways in, use any of them:

1. **Push**: eSSL / ZKTeco machines with "ADMS" or "Cloud server" send each punch to
   ``https://your-site/iclock/cdata`` by themselves.
2. **Pull**: the panel reads punches from a machine on the office network
   (``pip install "tungsten-hr[zk]"``), from the Devices screen or with ``pull_all(db)``.
3. **API or file**: POST punches to ``<panel>/api/hr/punches``, or upload a CSV / Excel file
   on the Punches screen.

The first punch of a day is the check-in, the last one the check-out.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from fastapi import Request
from sqlalchemy import or_, select

from .models import Attendance, BiometricDevice, Employee, Punch
from .service import fill_attendance

log = logging.getLogger("tungsten.hr")

TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
                "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M")


def parse_time(value: Any) -> dt.datetime:
    """A punch time from a machine, a file or JSON. Raises ValueError when it can't be read."""
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None, microsecond=0)
    text = str(value or "").strip()
    for fmt in TIME_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(text).replace(tzinfo=None, microsecond=0)
    except ValueError:
        raise ValueError(f"Can't read the time {text!r}. Use 2026-11-02 09:15:00.") from None


def find_employee(db: Any, person: str) -> Employee | None:
    """The employee with this machine ID, or else this employee code."""
    person = str(person).strip()
    if not person:
        return None
    rows = db.scalars(select(Employee).where(or_(Employee.biometric_id == person,
                                                 Employee.code == person.upper()))).all()
    return next((e for e in rows if e.biometric_id == person), rows[0] if rows else None)


def apply_punch(db: Any, employee_id: int, at: dt.datetime) -> Attendance:
    """Put one punch on the day's attendance: the earliest is the check-in, the latest the check-out."""
    row = db.scalars(select(Attendance).where(Attendance.employee_id == employee_id,
                                              Attendance.date == at.date())).first()
    if row is None:
        row = Attendance(employee_id=employee_id, date=at.date(), status="present", source="device")
        db.add(row)
    elif row.source == "leave" or row.status in ("absent", "leave", "holiday"):
        row.status, row.source = "present", "device"  # they came in after all
    time = at.time().replace(microsecond=0)
    if row.check_in is None:
        row.check_in = time
    elif time < row.check_in:
        row.check_out = row.check_out or row.check_in
        row.check_in = time
    elif time > row.check_in and (row.check_out is None or time > row.check_out):
        row.check_out = time
    if row.status == "half_day" and row.source == "device":
        row.status = "present"  # worked out again below from the new hours
    fill_attendance(db, row)
    db.flush()
    return row


def save_punch(db: Any, person: Any, at: Any, *, device: BiometricDevice | None = None,
               source: str = "api") -> tuple[Punch | None, bool]:
    """Save a punch and update attendance. Returns ``(punch, is_new)``; a repeat is skipped.

    Punches for an unknown person are kept and used once an employee gets that machine ID.
    Flushed, not committed.
    """
    person = str(person or "").strip()[:50]
    if not person:
        raise ValueError("Send the person's machine ID or employee code.")
    at = parse_time(at)
    existing = db.scalars(select(Punch).where(Punch.person == person, Punch.punched_at == at)).first()
    if existing is not None:
        return existing, False
    employee = find_employee(db, person)
    punch = Punch(person=person, punched_at=at, employee_id=employee.id if employee else None,
                  device_id=device.id if device else None, source=source)
    db.add(punch)
    db.flush()
    if employee is not None:
        apply_punch(db, employee.id, at)
    if device is not None and (device.last_punch_at is None or at > device.last_punch_at):
        device.last_punch_at = at
    return punch, True


def link_punches(db: Any, employee: Employee) -> int:
    """Give an employee the punches that came in before their machine ID was set. Returns how many."""
    keys = [k for k in (employee.biometric_id, employee.code) if k]
    if not keys or employee.id is None:
        return 0
    orphans = db.scalars(select(Punch).where(Punch.employee_id.is_(None), Punch.person.in_(keys))
                         .order_by(Punch.punched_at)).all()
    for punch in orphans:
        punch.employee_id = employee.id
        apply_punch(db, employee.id, punch.punched_at)
    return len(orphans)


# ---------------------------------------------------------------------- 1. push (ADMS / iclock)
def device_for_push(db: Any, serial: str, auto_accept: bool = False) -> BiometricDevice | None:
    """The machine with this serial number. An unknown one is added, switched off until you turn it on."""
    serial = (serial or "").strip()[:64]
    if not serial:
        return None
    device = db.scalars(select(BiometricDevice).where(BiometricDevice.serial_number == serial)).first()
    if device is None:
        device = BiometricDevice(name=f"Machine {serial}", serial_number=serial, is_active=auto_accept)
        db.add(device)
        log.info("New biometric machine %s %s", serial, "accepted" if auto_accept else "waiting to be turned on")
    device.last_seen_at = dt.datetime.now().replace(microsecond=0)
    db.flush()
    return device


def adms_options(serial: str) -> str:
    """What the machine asks for when it starts: send attendance logs right away."""
    return "\n".join([
        f"GET OPTION FROM: {serial}", "ATTLOGStamp=None", "OPERLOGStamp=9999", "ATTPHOTOStamp=None",
        "ErrorDelay=30", "Delay=10", "TransTimes=00:00;14:05", "TransInterval=1", "TransFlag=TransData AttLog",
        "Realtime=1", "Encrypt=None",
    ]) + "\n"


def adms_attlog(db: Any, device: BiometricDevice, body: str) -> int:
    """Save the lines of an ATTLOG upload (``PIN<TAB>2026-11-02 09:15:00<TAB>...``). Returns how many lines."""
    count = 0
    for line in body.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 2 or not parts[0].strip():
            continue
        count += 1
        try:
            save_punch(db, parts[0], parts[1], device=device, source="push")
        except ValueError:
            log.warning("Skipped a punch line from %s: %r", device.serial_number, line[:100])
    return count


def add_push_routes(app: Any, panel: Any, plugin: Any) -> None:
    """``/iclock/...``: where eSSL / ZKTeco machines send punches. At the site root, as machines expect."""
    from fastapi.responses import PlainTextResponse
    from starlette.concurrency import run_in_threadpool

    def text(body: str, status: int = 200) -> PlainTextResponse:
        return PlainTextResponse(body, status_code=status)

    async def cdata(request: Request):
        serial = request.query_params.get("SN", "")
        body = (await request.body()).decode("utf-8", errors="replace") if request.method == "POST" else ""
        table = (request.query_params.get("table") or "").upper()

        def work(db: Any) -> tuple[str, int]:
            device = device_for_push(db, serial, plugin.auto_accept_devices)
            if device is None:
                return "Send SN", 400
            if not device.is_active:
                db.commit()
                return "Turn this machine on in the panel first", 403
            if request.method == "GET":
                db.commit()
                return adms_options(serial), 200
            count = adms_attlog(db, device, body) if table == "ATTLOG" else len(body.splitlines())
            db.commit()
            return f"OK: {count}", 200

        return text(*await run_in_threadpool(panel.with_session, work))

    async def getrequest(request: Request):
        serial = request.query_params.get("SN", "")

        def touch(db: Any) -> None:
            if device_for_push(db, serial, plugin.auto_accept_devices) is not None:
                db.commit()

        await run_in_threadpool(panel.with_session, touch)
        return text("OK")

    async def devicecmd(request: Request):
        return text("OK")

    for prefix in dict.fromkeys(("/iclock", "/" + plugin.push_path.strip("/"))):
        for name in ("cdata", "cdata.aspx"):
            app.add_api_route(f"{prefix}/{name}", cdata, methods=["GET", "POST"], include_in_schema=False)
        for name in ("getrequest", "getrequest.aspx"):
            app.add_api_route(f"{prefix}/{name}", getrequest, methods=["GET"], include_in_schema=False)
        for name in ("devicecmd", "devicecmd.aspx"):
            app.add_api_route(f"{prefix}/{name}", devicecmd, methods=["POST"], include_in_schema=False)


# ---------------------------------------------------------------------- 2. pull (office network)
def _zk_class() -> Any:
    try:
        from zk import ZK  # pyzk
    except ImportError:
        raise RuntimeError('Pulling needs pyzk: pip install "tungsten-hr[zk]"') from None
    return ZK


def pull_device(db: Any, device: BiometricDevice, zk_class: Any = None, timeout: int = 10) -> tuple[int, int]:
    """Read the punches stored on a machine over the network. Returns ``(new, total read)``.

    Only punches newer than the last one saved are kept, so it is safe to run often. Flushed, not committed.
    """
    if not device.ip_address:
        raise RuntimeError(f"{device.name} has no IP address.")
    zk = (zk_class or _zk_class())(device.ip_address, port=device.port or 4370, timeout=timeout,
                                   password=device.password or 0, ommit_ping=True)
    conn = zk.connect()
    try:
        logs = conn.get_attendance() or []
    finally:
        conn.disconnect()
    since = device.last_punch_at
    new = 0
    for item in logs:
        at = parse_time(item.timestamp)
        if since is not None and at <= since:
            continue
        _, created = save_punch(db, item.user_id, at, device=device, source="pull")
        new += created
    device.last_seen_at = dt.datetime.now().replace(microsecond=0)
    db.flush()
    return new, len(logs)


def pull_all(db: Any, zk_class: Any = None) -> dict[str, Any]:
    """Pull every active machine that has an IP address (for a cron job). Errors are logged, not raised."""
    results: dict[str, Any] = {}
    devices = db.scalars(select(BiometricDevice).where(BiometricDevice.is_active.is_(True),
                                                       BiometricDevice.ip_address.is_not(None))).all()
    for device in devices:
        try:
            results[device.name] = pull_device(db, device, zk_class)[0]
            db.commit()
        except Exception as exc:  # one dead machine must not stop the others
            db.rollback()
            log.exception("Could not pull punches from %s", device.name)
            results[device.name] = str(exc)
    return results


# ---------------------------------------------------------------------- 3. API
def add_api_route(app: Any, panel: Any, plugin: Any) -> None:
    """``POST <panel>/api/hr/punches`` with the ``X-HR-Token`` header."""
    import hmac

    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool

    @app.post("/api/hr/punches")
    async def api_punches(request: Request):
        token = request.headers.get("x-hr-token", "")
        if not hmac.compare_digest(token.encode(), (plugin.api_token or "").encode()):
            return JSONResponse({"error": "Wrong token"}, status_code=401)
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse({"error": "Send JSON"}, status_code=422)
        items = payload.get("punches", [payload]) if isinstance(payload, dict) else payload
        if not isinstance(items, list) or not items:
            return JSONResponse({"error": "Send {\"punches\": [{\"employee\": ..., \"time\": ...}]}"},
                                status_code=422)

        def work(db: Any) -> dict:
            saved = repeated = 0
            errors, unknown = [], set()
            for i, item in enumerate(items[:5000]):
                if not isinstance(item, dict):
                    errors.append({"row": i, "error": "Each punch must be an object"})
                    continue
                person = item.get("employee") or item.get("code") or item.get("device_user_id") or item.get("pin")
                device = None
                if item.get("device"):
                    device = db.scalars(select(BiometricDevice).where(
                        BiometricDevice.serial_number == str(item["device"]))).first()
                try:
                    punch, created = save_punch(db, person, item.get("time"), device=device, source="api")
                except ValueError as exc:
                    errors.append({"row": i, "error": str(exc)})
                    continue
                saved += created
                repeated += not created
                if punch is not None and punch.employee_id is None:
                    unknown.add(punch.person)
            db.commit()
            return {"saved": saved, "repeated": repeated, "unknown_people": sorted(unknown), "errors": errors}

        return JSONResponse(await run_in_threadpool(panel.with_session, work))
