"""Tungsten shop demo.

Run:
    pip install -e ".[dev]"
    python -m examples.shop.seed          # create shop.db with demo data
    uvicorn examples.shop.app:app --reload
Then open http://127.0.0.1:8000/admin and sign in with admin@example.com / password

To try the async engine: DATABASE_URL=sqlite+aiosqlite:///shop.db uvicorn examples.shop.app:app
"""

import os

from .factory import create_app

app, panel = create_app(os.environ.get("DATABASE_URL", "sqlite:///shop.db"))
