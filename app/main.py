"""Our Little House: FastAPI backend.

Serves the 3D page, stores lists and furniture layout in SQLite, and pushes the
full state to every open browser over a WebSocket whenever anything changes.
"""
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI

DB_PATH = Path(os.environ.get("HOUSE_DB", "data/house.db"))


# ---------- database ----------
@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS items(
              id TEXT PRIMARY KEY, room TEXT NOT NULL, text TEXT NOT NULL,
              done INTEGER NOT NULL DEFAULT 0, fav INTEGER NOT NULL DEFAULT 0,
              ts INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS layout(piece TEXT PRIMARY KEY, x REAL, z REAL, r REAL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
            """
        )


def snapshot() -> dict:
    with db() as con:
        items = [
            {"id": r["id"], "room": r["room"], "text": r["text"], "done": bool(r["done"]),
             "fav": bool(r["fav"]), "ts": r["ts"]}
            for r in con.execute("SELECT * FROM items")
        ]
        layout = [dict(r) for r in con.execute("SELECT * FROM layout")]
        started = con.execute("SELECT value FROM meta WHERE key='started'").fetchone()
    return {"items": items, "layout": layout, "started": int(started[0]) if started else None}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Our Little House", lifespan=lifespan)


@app.get("/healthz")
def health():
    return {"ok": True}
