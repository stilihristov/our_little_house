"""Our Little House: FastAPI backend.

Serves the 3D page, stores lists and furniture layout in SQLite, and pushes the
full state to every open browser over a WebSocket whenever anything changes.
Access is protected by one shared password (HOUSE_PASSWORD).
"""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Optional

from fastapi import Cookie, FastAPI, HTTPException, Response
from pydantic import BaseModel

DB_PATH = Path(os.environ.get("HOUSE_DB", "data/house.db"))
PASSWORD = os.environ.get("HOUSE_PASSWORD", "change-me")
SECRET = os.environ.get("HOUSE_SECRET") or secrets.token_hex(32)  # set it in production so logins survive restarts
COOKIE = "house_session"
COOKIE_DAYS = 180

SEED_ITEMS = [
    ("movies", "Tekkonkinkreet (2006)", True, True),
    ("movies", "Mind Game (2004)", False, False),
    ("movies", "Mutafukaz (2017)", False, False),
    ("movies", "The Night Is Short, Walk On Girl (2017)", False, True),
    ("movies", "Children of the Sea (2019)", False, False),
    ("movies", "Paprika (2006)", False, False),
    ("movies", "Ping Pong the Animation (series)", False, False),
    ("movies", "Redline (2009)", False, False),
]


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
        if not con.execute("SELECT 1 FROM meta WHERE key='started'").fetchone():
            now = int(time.time() * 1000)
            con.execute("INSERT INTO meta VALUES('started', ?)", (str(now),))
            for n, (room, text, done, fav) in enumerate(SEED_ITEMS):
                con.execute(
                    "INSERT INTO items(id,room,text,done,fav,ts) VALUES(?,?,?,?,?,?)",
                    (f"seed{n}", room, text, int(done), int(fav), now - n),
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


# ---------- auth: one shared password, signed cookie ----------
def sign(value: str) -> str:
    mac = hmac.new(SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{mac}"


def valid(token: Optional[str]) -> bool:
    if not token or "." not in token:
        return False
    value, mac = token.rsplit(".", 1)
    expected = hmac.new(SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return False
    try:
        return int(value) > time.time()
    except ValueError:
        return False


def require(token: Optional[str]) -> None:
    if not valid(token):
        raise HTTPException(401, "Sign in first")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Our Little House", lifespan=lifespan)


# ---------- models ----------
class Login(BaseModel):
    password: str


# ---------- routes ----------
@app.post("/api/login")
def login(body: Login, response: Response):
    if not hmac.compare_digest(body.password, PASSWORD):
        raise HTTPException(401, "Wrong password")
    expires = int(time.time()) + COOKIE_DAYS * 86400
    response.set_cookie(COOKIE, sign(str(expires)), max_age=COOKIE_DAYS * 86400,
                        httponly=True, samesite="lax", secure=os.environ.get("HOUSE_HTTPS") == "1")
    return {"ok": True}


@app.get("/api/me")
def me(house_session: Optional[str] = Cookie(None)):
    require(house_session)
    return {"ok": True}


@app.get("/healthz")
def health():
    return {"ok": True}
