"""Our Little House: FastAPI backend.

Serves the 3D page, stores lists and furniture layout in SQLite, and pushes the
full state to every open browser over a WebSocket whenever anything changes.
"""

from fastapi import FastAPI


app = FastAPI(title="Our Little House")


@app.get("/healthz")
def health():
    return {"ok": True}
