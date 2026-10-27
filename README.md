# Our Little House

A 3D plaster house for two. Each room holds a shared list (movies, food, dates, places), the furniture can be rearranged, and the house grows over time. FastAPI serves the page, stores everything in SQLite and pushes changes live over a WebSocket.

```
app/
  main.py           FastAPI app: auth, REST API, WebSocket, SQLite
  static/index.html the whole 3D front end (three.js from a CDN)
Dockerfile
```

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
HOUSE_PASSWORD=1234 uvicorn app.main:app --reload
```

Open http://localhost:8000 and enter the PIN. The database is created at `data/house.db` on first start, seeded with the movie list, and today is saved as day 1.

## Settings (environment variables)

| Variable | What it does | Default |
|---|---|---|
| `HOUSE_PASSWORD` | The shared 4-digit PIN for both of you | `change-me` |
| `HOUSE_SECRET` | Signs the login cookie. Set it, or everyone is logged out on every restart | random each start |
| `HOUSE_DB` | Path to the SQLite file | `data/house.db` |
| `HOUSE_HTTPS` | Set to `1` behind HTTPS so the cookie is marked secure | off |

Generate a secret with `python -c "import secrets; print(secrets.token_hex(32))"`.

## API

All routes need the login cookie except `/api/login` and `/healthz`.

- `POST /api/login` `{password}` (5 wrong tries per device per 15 minutes, 30 overall per hour)
- `GET /api/state` returns `{items, layout, started}`
- `POST /api/items` `{room, text}` · `PATCH /api/items/{id}` `{text?, done?, fav?}` · `DELETE /api/items/{id}`
- `PUT /api/layout/{piece}` `{x, z, r}` · `DELETE /api/layout` (reset)
- `WS /ws` sends the full state on connect and after every change
