"""
Management portal: sign-in page, tabbed pages and the read-only API, all behind login.

Run:  uvicorn portal:app --host 0.0.0.0 --port 8002
Open: http://localhost:8002
"""
from pathlib import Path

from fastapi.responses import FileResponse, RedirectResponse

import auth_portal
from crm_api import app
from admin_users import router as admin_router
from insights import router as insights_router

app.include_router(insights_router)
app.include_router(admin_router)
auth_portal.install(app)
HERE = Path(__file__).resolve().parent
NOCACHE = {"Cache-Control": "no-store"}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/portal")


@app.get("/portal", include_in_schema=False)
def portal():
    return FileResponse(HERE / "portal.html", headers=NOCACHE)


@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(HERE / "login.html", headers=NOCACHE)
