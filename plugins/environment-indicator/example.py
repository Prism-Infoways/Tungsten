"""Try the environment indicator.

    pip install -e . -e plugins/environment-indicator uvicorn
    APP_ENV=staging uvicorn plugins.environment-indicator.example:app --reload     (from the repo root)

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password.
Without APP_ENV the badge says Local on 127.0.0.1, and Live on any other address.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_environment_indicator import EnvironmentIndicatorPlugin

from tungsten import Auth, Panel, hash_password


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


engine = create_engine("sqlite:///environment_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

panel = Panel(path="/admin", session_factory=Session, secret_key="dev-only", auth=Auth(User),
              brand_name="Acme admin", spa=True)
panel.plugin(EnvironmentIndicatorPlugin(git_branch=True))
panel.create_tables(engine)

with Session() as db:
    if db.scalar(select(User)) is None:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.commit()

app = FastAPI()
panel.mount(app)


@app.get("/")
def home():
    return RedirectResponse(panel.path + "/")
