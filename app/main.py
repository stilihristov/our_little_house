"""Our Little House: FastAPI backend.

Serves the 3D page, stores lists and furniture layout in SQLite, and pushes the
full state to every open browser over a WebSocket whenever anything changes.
Access is protected by one shared password (HOUSE_PASSWORD).
"""
import asyncio
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import Cookie, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DB_PATH = Path(os.environ.get("HOUSE_DB", "data/house.db"))
PASSWORD = os.environ.get("HOUSE_PASSWORD", "change-me")
SECRET = os.environ.get("HOUSE_SECRET") or secrets.token_hex(32)  # set it in production so logins survive restarts
COOKIE = "house_session"
COOKIE_DAYS = 180
STATIC = Path(__file__).parent / "static"

Room = Literal["movies", "food", "dates", "trips"]
PIECES = {"screen", "bench", "cube", "counter", "cylinder", "table", "stair", "sphere", "bed", "column"}

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
              ts INTEGER NOT NULL, done_at INTEGER);
            CREATE TABLE IF NOT EXISTS layout(piece TEXT PRIMARY KEY, x REAL, z REAL, r REAL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
            """
        )
        if not con.execute("SELECT 1 FROM meta WHERE key='started'").fetchone():
            now = int(time.time() * 1000)
            con.execute("INSERT INTO meta VALUES('started', ?)", (str(now),))
            for n, (room, text, done, fav) in enumerate(SEED_ITEMS):
                con.execute(
                    "INSERT INTO items(id,room,text,done,fav,ts,done_at) VALUES(?,?,?,?,?,?,?)",
                    (f"seed{n}", room, text, int(done), int(fav), now - n, now if done else None),
                )


def snapshot() -> dict:
    with db() as con:
        items = [
            {"id": r["id"], "room": r["room"], "text": r["text"], "done": bool(r["done"]),
             "fav": bool(r["fav"]), "ts": r["ts"], "doneAt": r["done_at"]}
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


# ---------- live sync ----------
class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def broadcast(self) -> None:
        state = snapshot()
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(state)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


hub = Hub()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Our Little House", lifespan=lifespan)


# ---------- models ----------
class Login(BaseModel):
    password: str


class NewItem(BaseModel):
    room: Room
    text: str = Field(min_length=1, max_length=200)


class ItemPatch(BaseModel):
    text: Optional[str] = Field(default=None, min_length=1, max_length=200)
    done: Optional[bool] = None
    fav: Optional[bool] = None
    doneAt: Optional[int] = None


class Place(BaseModel):
    x: float = Field(ge=-4, le=4)
    z: float = Field(ge=-4, le=4)
    r: float


# ---------- login throttling: cap wrong guesses so the PIN can't be brute-forced ----------
FAILS: dict[str, list[float]] = {}
IP_MAX, IP_WINDOW = 5, 15 * 60          # per device: 5 wrong tries per 15 minutes
ALL_MAX, ALL_WINDOW = 30, 60 * 60       # everyone together: 30 wrong tries per hour


def client_ip(request: Request) -> str:
    return request.headers.get("fly-client-ip") or (request.client.host if request.client else "?")


def recent(key: str, window: int) -> list[float]:
    now = time.time()
    FAILS[key] = [t for t in FAILS.get(key, []) if t > now - window]
    return FAILS[key]


# ---------- routes ----------
@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    ip = client_ip(request)
    if len(recent(ip, IP_WINDOW)) >= IP_MAX or len(recent("*", ALL_WINDOW)) >= ALL_MAX:
        raise HTTPException(429, "Too many tries")
    if not hmac.compare_digest(body.password, PASSWORD):
        FAILS[ip].append(time.time())
        FAILS["*"].append(time.time())
        raise HTTPException(401, "Wrong password")
    expires = int(time.time()) + COOKIE_DAYS * 86400
    response.set_cookie(COOKIE, sign(str(expires)), max_age=COOKIE_DAYS * 86400,
                        httponly=True, samesite="lax", secure=os.environ.get("HOUSE_HTTPS") == "1")
    return {"ok": True}


@app.get("/api/me")
def me(house_session: Optional[str] = Cookie(None)):
    require(house_session)
    return {"ok": True}


@app.get("/api/state")
def state(house_session: Optional[str] = Cookie(None)):
    require(house_session)
    return snapshot()


@app.post("/api/items", status_code=201)
async def add_item(body: NewItem, house_session: Optional[str] = Cookie(None)):
    require(house_session)
    item_id = "i" + secrets.token_hex(6)
    with db() as con:
        con.execute("INSERT INTO items(id,room,text,ts) VALUES(?,?,?,?)",
                    (item_id, body.room, body.text.strip(), int(time.time() * 1000)))
    await hub.broadcast()
    return {"id": item_id}


@app.patch("/api/items/{item_id}")
async def update_item(item_id: str, body: ItemPatch, house_session: Optional[str] = Cookie(None)):
    require(house_session)
    fields = body.model_dump(exclude_unset=True)
    cols = {"text": "text", "done": "done", "fav": "fav", "doneAt": "done_at"}
    sets = [(cols[k], int(v) if isinstance(v, bool) else v) for k, v in fields.items()]
    if "done" in fields and "doneAt" not in fields:
        sets.append(("done_at", int(time.time() * 1000) if fields["done"] else None))
    if not sets:
        return {"ok": True}
    with db() as con:
        cur = con.execute(f"UPDATE items SET {', '.join(c + '=?' for c, _ in sets)} WHERE id=?",
                          [v for _, v in sets] + [item_id])
        if cur.rowcount == 0:
            raise HTTPException(404, "No such item")
    await hub.broadcast()
    return {"ok": True}


@app.delete("/api/items/{item_id}", status_code=204)
async def delete_item(item_id: str, house_session: Optional[str] = Cookie(None)):
    require(house_session)
    with db() as con:
        con.execute("DELETE FROM items WHERE id=?", (item_id,))
    await hub.broadcast()
    return Response(status_code=204)


@app.put("/api/layout/{piece}")
async def place_piece(piece: str, body: Place, house_session: Optional[str] = Cookie(None)):
    require(house_session)
    if piece not in PIECES:
        raise HTTPException(404, "No such piece")
    with db() as con:
        con.execute("INSERT INTO layout VALUES(?,?,?,?) ON CONFLICT(piece) DO UPDATE SET x=excluded.x, z=excluded.z, r=excluded.r",
                    (piece, body.x, body.z, body.r))
    await hub.broadcast()
    return {"ok": True}


@app.delete("/api/layout", status_code=204)
async def reset_layout(house_session: Optional[str] = Cookie(None)):
    require(house_session)
    with db() as con:
        con.execute("DELETE FROM layout")
    await hub.broadcast()
    return Response(status_code=204)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    if not valid(ws.cookies.get(COOKIE)):
        await ws.close(code=4401)
        return
    hub.clients.add(ws)
    try:
        await ws.send_json(snapshot())
        while True:
            # clients only listen; this keeps the connection open and notices disconnects
            await asyncio.wait_for(ws.receive_text(), timeout=None)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        hub.clients.discard(ws)


@app.get("/healthz")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
