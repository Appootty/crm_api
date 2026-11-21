"""
Serves the dashboard page on top of the read-only API (crm_api.py).

Run:  uvicorn crm_dashboard:app --host 0.0.0.0 --port 8001
Open: http://localhost:8001/dashboard
"""
from pathlib import Path
from fastapi.responses import FileResponse
from crm_api import app  # all endpoints stay available
from insights import router as insights_router

app.include_router(insights_router)


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(Path(__file__).parent / "dashboard.html")


@app.get("/insights-page", include_in_schema=False)
def insights_page():
    return FileResponse(Path(__file__).parent / "insights.html")
