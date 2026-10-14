"""Durable background jobs: worker process, retries with backoff, heartbeats and recovery (issue #73)."""

from __future__ import annotations

import datetime as dt
import threading

import pytest
from sqlalchemy import String, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from tungsten import Auth, Panel, hash_password
from tungsten.cli import main
from tungsten.jobs import background_context
from tungsten.models import Job


class Base(DeclarativeBase):
    pass


class JUser(Base):
    __tablename__ = "jw_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(100))
    password: Mapped[str] = mapped_column(String(200))


ran: list[str] = []


def make(tmp_path, mode="thread"):
    ran.clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as db:
        db.add(JUser(name="Ann", email="ann@x.com", password=hash_password("password")))
        db.commit()
    panel = Panel(session_factory=Session, secret_key="s", auth=Auth(JUser), jobs=mode)
    panel.create_tables(engine)
    panel.jobs.register("hello", lambda job: ran.append(job.payload["who"]) or {"ok": True})
    return panel, Session


def dispatch(panel, Session, kind, **payload):
    with Session() as db:
        return panel.jobs.dispatch(background_context(panel, db, "1"), kind, payload, name=kind).id


def job(Session, job_id):
    with Session() as db:
        return db.get(Job, job_id)


def test_worker_mode_only_queues_and_the_worker_runs(tmp_path):
    panel, Session = make(tmp_path, "worker")
    job_id = dispatch(panel, Session, "hello", who="Ann")
    panel.jobs.wait()
    assert ran == [] and job(Session, job_id).status == "queued"
    assert panel.jobs.work(once=True) == 1
    j = job(Session, job_id)
    assert ran == ["Ann"] and j.status == "done" and j.attempts == 1 and j.locked_by is None


def test_a_job_is_claimed_once(tmp_path):
    panel, Session = make(tmp_path, "worker")
    job_id = dispatch(panel, Session, "hello", who="Ann")
    with Session() as a, Session() as b:
        assert panel.jobs._begin(a, job_id) is not None
        assert panel.jobs._begin(b, job_id) is None  # another process got it first
    panel.jobs._released(job_id)


def test_retry_with_backoff(tmp_path):
    panel, Session = make(tmp_path, "worker")
    tries = []

    def flaky(job):
        tries.append(job.job.attempts)
        if len(tries) < 3:
            raise RuntimeError(f"try {len(tries)} failed")
        return {"done": True}

    panel.jobs.register("flaky", flaky, max_attempts=3, backoff=[0, 0])
    job_id = dispatch(panel, Session, "flaky")
    for _ in range(3):
        panel.jobs.work(once=True)
    j = job(Session, job_id)
    assert tries == [1, 2, 3] and j.status == "done" and j.attempts == 3


def test_backoff_waits(tmp_path):
    panel, Session = make(tmp_path, "worker")
    panel.jobs.register("boom", lambda job: 1 / 0, max_attempts=2, backoff=3600)
    job_id = dispatch(panel, Session, "boom")
    panel.jobs.work(once=True)
    j = job(Session, job_id)
    assert j.status == "queued" and j.attempts == 1 and j.available_at > dt.datetime.now()
    assert panel.jobs.work(once=True) == 0  # not yet
    assert panel.jobs.backoff_for("boom", 1) == 3600


def test_out_of_tries_fails_and_retry_queues_again(tmp_path):
    panel, Session = make(tmp_path, "thread")
    panel.jobs.register("boom", lambda job: 1 / 0)
    job_id = dispatch(panel, Session, "boom")
    panel.jobs.wait()
    assert job(Session, job_id).status == "failed"
    panel.jobs.register("boom", lambda job: {"fixed": True})
    assert panel.jobs.retry(job_id) is True
    panel.jobs.wait()
    j = job(Session, job_id)
    assert j.status == "done" and j.attempts == 2 and j.error is None
    assert panel.jobs.retry(job_id) is False  # not failed


def test_recover_requeues_stale_jobs_and_leaves_live_ones(tmp_path):
    panel, Session = make(tmp_path, "worker")
    panel.jobs.register("long", lambda job: None, max_attempts=2)
    stale, live, last_try = (dispatch(panel, Session, "long") for _ in range(3))
    old = dt.datetime.now() - dt.timedelta(minutes=10)
    with Session() as db:
        for job_id, beat, attempts in ((stale, old, 1), (live, dt.datetime.now(), 1), (last_try, old, 2)):
            j = db.get(Job, job_id)
            j.status, j.heartbeat_at, j.attempts, j.locked_by = "running", beat, attempts, "gone:1:x"
        db.commit()
    assert panel.jobs.recover() == {"requeued": 1, "failed": 1}
    assert job(Session, stale).status == "queued"
    assert job(Session, live).status == "running"  # another process is still on it
    assert job(Session, last_try).status == "failed"
    assert panel.jobs.fail_unfinished() == 0


def test_heartbeat_thread_updates_running_jobs(tmp_path):
    panel, Session = make(tmp_path, "worker")
    gate = threading.Event()
    panel.jobs.heartbeat_seconds = 0.05
    panel.jobs.register("slow", lambda job: gate.wait(5))
    job_id = dispatch(panel, Session, "slow")
    worker = threading.Thread(target=panel.jobs.work, kwargs={"once": True})
    worker.start()
    try:
        first = None
        for _ in range(100):
            j = job(Session, job_id)
            if j.status == "running" and j.heartbeat_at is not None:
                if first is None:
                    first = j.heartbeat_at
                elif j.heartbeat_at > first:
                    break
            threading.Event().wait(0.02)
        else:
            pytest.fail("no heartbeat")
    finally:
        gate.set()
        worker.join(10)
    assert job(Session, job_id).status == "done"


def test_create_tables_adds_new_columns_to_an_old_jobs_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tungsten_jobs (id INTEGER PRIMARY KEY, kind VARCHAR(50), name VARCHAR(255), "
                          "user_id VARCHAR(64), tenant_key VARCHAR(64), status VARCHAR(20), payload JSON, "
                          "result JSON, total INTEGER, processed INTEGER, failed INTEGER, error TEXT, "
                          "created_at DATETIME, started_at DATETIME, finished_at DATETIME)"))
        conn.execute(text("INSERT INTO tungsten_jobs (id, kind, status) VALUES (1, 'export', 'done')"))
    Panel(engine=engine, secret_key="s").create_tables(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("tungsten_jobs")}
    assert {"attempts", "max_attempts", "available_at", "locked_by", "heartbeat_at"} <= cols
    with engine.connect() as conn:
        assert conn.execute(text("SELECT attempts, max_attempts FROM tungsten_jobs")).one() == (0, 1)


def test_cli(tmp_path, monkeypatch, capsys):
    import sys
    import types

    panel, Session = make(tmp_path, "worker")
    job_id = dispatch(panel, Session, "hello", who="Cli")
    module = types.ModuleType("jw_app")
    module.panel = panel
    monkeypatch.setitem(sys.modules, "jw_app", module)
    assert main(["jobs:work", "--panel", "jw_app:panel", "--once"]) == 0
    assert ran == ["Cli"] and "Started 1 job(s)" in capsys.readouterr().out
    with Session() as db:
        db.get(Job, job_id).status = "failed"
        db.commit()
    assert main(["jobs:retry", "1", "--panel", "jw_app:panel"]) == 0
    with pytest.raises(SystemExit):
        main(["jobs:retry", "999", "--panel", "jw_app:panel"])
