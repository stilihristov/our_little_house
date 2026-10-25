# Our Little House

A 3D plaster house for two. Each room holds a shared list (movies, food, dates, places), the furniture can be rearranged, and the house grows over time. FastAPI serves the page, stores everything in SQLite and pushes changes live over a WebSocket.

```
app/
  main.py           FastAPI app: auth, REST API, WebSocket, SQLite
  static/index.html the whole 3D front end (three.js from a CDN)
```

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
HOUSE_PASSWORD=1234 uvicorn app.main:app --reload
```

Open http://localhost:8000 and enter the password. The database is created at `data/house.db` on first start, seeded with the movie list, and today is saved as day 1.
