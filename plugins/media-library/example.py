"""Try the media library plugin (with the blog and help desk, to see files reused across plugins).

    pip install -e . -e plugins/media-library -e plugins/blog -e plugins/tickets uvicorn
    cd plugins/media-library && uvicorn example:app --reload

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password.
Upload files in "Media library", then open a blog post and press "Choose from library" under the cover.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_blog import BlogPlugin
from tungsten_media_library import MediaLibraryPlugin
from tungsten_tickets import TicketsPlugin

from tungsten import Auth, LocalStorage, Panel, hash_password


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


engine = create_engine("sqlite:///media_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

panel = Panel(path="/admin", session_factory=Session, secret_key="dev-only", auth=Auth(User),
              # public=True: blog images show on the public blog without signing in
              storage=LocalStorage("media_demo_storage", public=True),
              brand_name="Tungsten Media", spa=True)
panel.plugin(MediaLibraryPlugin())
panel.plugin(BlogPlugin(site_name="Acme", site_url="http://127.0.0.1:8000"))
panel.plugin(TicketsPlugin())
panel.create_tables(engine)

with Session() as db:
    if db.scalar(select(User)) is None:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.commit()

app = FastAPI()


@app.get("/")
def home():
    return RedirectResponse("/admin")


panel.mount(app)
